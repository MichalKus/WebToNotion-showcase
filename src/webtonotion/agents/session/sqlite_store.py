"""SQLite-backed :class:`SessionStore` implementation.

Persists chat sessions and their append-only message history in a single SQLite
file (WAL mode). Message payloads are stored exactly as Pydantic AI serializes
them — ``to_jsonable_python(result.new_messages())`` on write,
``ModelMessagesTypeAdapter.validate_python(...)`` on read — so tool calls, tool
returns, retries, and usage round-trip without a translation layer of ours.

``sqlite3`` is blocking, so every database operation is wrapped in
``asyncio.to_thread`` to keep the event loop free. The ``PRIMARY KEY
(session_id, seq)`` on ``messages`` turns a concurrent-write race into a
``sqlite3.IntegrityError``, which is surfaced as :class:`SessionConflictError`.

``load_history``'s row-count limit can truncate mid tool-call/return pair;
:func:`_drop_to_exchange_boundary` trims the result to the first genuine user
turn so callers never see history opening with an orphaned tool return.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic_ai import ModelMessage, ModelMessagesTypeAdapter
from pydantic_ai.messages import ModelRequest, UserPromptPart

from webtonotion.config.settings import settings

from .store import Session, SessionConflictError, SessionStore

_BUSY_TIMEOUT_MS = 5000

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
  id                    TEXT PRIMARY KEY,
  conversation_id       TEXT NOT NULL,
  confirmed_database_id TEXT,
  created_at            TEXT NOT NULL,
  last_active_at        TEXT NOT NULL
)
"""

_CREATE_MESSAGES = """
CREATE TABLE IF NOT EXISTS messages (
  session_id TEXT NOT NULL,
  seq        INTEGER NOT NULL,
  payload    TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (session_id, seq)
)
"""


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _drop_to_exchange_boundary(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Drop leading messages so history never opens mid tool-call/return pair.

    A row-count ``LIMIT`` can cut between a ``ModelResponse``'s tool call and the
    following ``ModelRequest``'s tool return, leaving the truncated history open
    with an orphaned ``ToolReturnPart`` that OpenAI-compatible providers reject.
    Pydantic AI's own repair (``sanitize_messages``) only strips dangling tool
    *calls* from the tail, not orphaned tool *returns* at the head, so this store
    trims forward to the first genuine user turn instead: a ``ModelRequest``
    carrying a ``UserPromptPart`` can never open with a bare tool return, since a
    request that does is, by construction, a reply to a prior tool call only.
    """
    for index, message in enumerate(messages):
        if isinstance(message, ModelRequest) and any(
            isinstance(part, UserPromptPart) for part in message.parts
        ):
            return messages[index:]
    return []


class SqliteStore(SessionStore):
    """Session and message-history store backed by stdlib ``sqlite3``."""

    def __init__(self, db_path: str | None = None) -> None:
        """Create a store rooted at ``db_path`` (defaults to ``settings``).

        Parent directories are created eagerly so a fresh ``cache/`` need not
        exist. Call :meth:`init_schema` (idempotent) before first use.
        """
        self._db_path = db_path if db_path is not None else settings.session_db_path

    def _connect(self) -> sqlite3.Connection:
        """Open a connection with WAL mode and a busy timeout set."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        return conn

    def _init_schema_sync(self) -> None:
        """Create the tables if they do not already exist."""
        conn = self._connect()
        try:
            with conn:
                conn.execute(_CREATE_SESSIONS)
                conn.execute(_CREATE_MESSAGES)
        finally:
            conn.close()

    async def init_schema(self) -> None:
        """Idempotently create the schema; safe to call on every startup."""
        await asyncio.to_thread(self._init_schema_sync)

    # ------------------------------------------------------------------
    # SessionStore interface
    # ------------------------------------------------------------------

    def _create_sync(self, conversation_id: str) -> Session:
        session_id = uuid4().hex
        now = _now_iso()
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO sessions "
                    "(id, conversation_id, confirmed_database_id, created_at, last_active_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (session_id, conversation_id, None, now, now),
                )
        finally:
            conn.close()
        created = datetime.fromisoformat(now)
        return Session(
            id=session_id,
            conversation_id=conversation_id,
            confirmed_database_id=None,
            created_at=created,
            last_active_at=created,
        )

    async def create(self, conversation_id: str) -> Session:
        """Create and return a new session for ``conversation_id``."""
        return await asyncio.to_thread(self._create_sync, conversation_id)

    def _get_sync(self, session_id: str) -> Session | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, conversation_id, confirmed_database_id, created_at, last_active_at "
                "FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return Session(
            id=row[0],
            conversation_id=row[1],
            confirmed_database_id=row[2],
            created_at=datetime.fromisoformat(row[3]),
            last_active_at=datetime.fromisoformat(row[4]),
        )

    async def get(self, session_id: str) -> Session | None:
        """Return the session, or ``None`` if it does not exist."""
        return await asyncio.to_thread(self._get_sync, session_id)

    def _next_seq_sync(self, session_id: str) -> int:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        finally:
            conn.close()
        return int(row[0])

    async def next_seq(self, session_id: str) -> int:
        """Return the sequence number the next appended message should use."""
        return await asyncio.to_thread(self._next_seq_sync, session_id)

    def _append_messages_sync(self, session_id: str, seq_start: int, payloads: list[Any]) -> None:
        now = _now_iso()
        rows = [
            (session_id, seq_start + offset, json.dumps(payload), now)
            for offset, payload in enumerate(payloads)
        ]
        conn = self._connect()
        try:
            with conn:
                conn.executemany(
                    "INSERT INTO messages (session_id, seq, payload, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    rows,
                )
        except sqlite3.IntegrityError as exc:
            raise SessionConflictError(
                f"Concurrent append to session {session_id!r} at seq {seq_start}"
            ) from exc
        finally:
            conn.close()

    async def append_messages(self, session_id: str, seq_start: int, payloads: list[Any]) -> None:
        """Append serialized messages as rows ``seq_start, seq_start + 1, ...``.

        All rows are inserted in one transaction; a primary-key collision on any
        ``(session_id, seq)`` rolls the whole batch back and raises
        :class:`SessionConflictError`.
        """
        await asyncio.to_thread(self._append_messages_sync, session_id, seq_start, payloads)

    def _load_history_sync(self, session_id: str, limit: int) -> list[ModelMessage]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT payload FROM messages WHERE session_id = ? ORDER BY seq DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        finally:
            conn.close()
        objects = [json.loads(row[0]) for row in reversed(rows)]
        history: list[ModelMessage] = ModelMessagesTypeAdapter.validate_python(objects)
        return _drop_to_exchange_boundary(history)

    async def load_history(self, session_id: str, limit: int) -> list[ModelMessage]:
        """Return the last ``limit`` messages in chronological order."""
        return await asyncio.to_thread(self._load_history_sync, session_id, limit)

    def _set_confirmed_database_sync(self, session_id: str, database_id: str | None) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "UPDATE sessions SET confirmed_database_id = ? WHERE id = ?",
                    (database_id, session_id),
                )
        finally:
            conn.close()

    async def set_confirmed_database(self, session_id: str, database_id: str | None) -> None:
        """Set (or clear, with ``None``) the session's confirmed write target."""
        await asyncio.to_thread(self._set_confirmed_database_sync, session_id, database_id)

    def _touch_sync(self, session_id: str) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "UPDATE sessions SET last_active_at = ? WHERE id = ?",
                    (_now_iso(), session_id),
                )
        finally:
            conn.close()

    async def touch(self, session_id: str) -> None:
        """Update ``last_active_at`` to now."""
        await asyncio.to_thread(self._touch_sync, session_id)

    def _delete_sync(self, session_id: str) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        finally:
            conn.close()

    async def delete(self, session_id: str) -> None:
        """Delete the session and all its messages."""
        await asyncio.to_thread(self._delete_sync, session_id)
