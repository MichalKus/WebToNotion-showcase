"""Session store interface.

Defines the abstract contract for persisting chat sessions and their message
history, plus the ``Session`` record and the conflict signal raised on a
concurrent-write race. Implementations live alongside this module (e.g.
``sqlite_store.py``); the API layer and the orchestrator depend only on this ABC,
so the backing store can move from SQLite to Postgres without touching callers.

Message payloads crossing this boundary are the Pydantic AI serialization
produced by ``to_jsonable_python(result.new_messages())`` and reloaded via
``ModelMessagesTypeAdapter.validate_python(...)`` — no translation layer of ours.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic_ai import ModelMessage


class SessionConflictError(Exception):
    """Raised when two turns append to one session concurrently.

    Two concurrent messages in a single conversation is a client bug, not
    something to merge. Implementations surface the primary-key collision on
    ``(session_id, seq)`` as this error; the chat route maps it to HTTP 409.
    """


class SessionNotFoundError(Exception):
    """Raised when a caller references a session id that does not exist.

    The chat route maps it to HTTP 404. Distinct from a brand-new session, which
    is created rather than looked up.
    """


@dataclass
class Session:
    """A chat session and its one-column write gate.

    ``confirmed_database_id`` is the entire confirm-gate: null means writes are
    blocked; a value means writes proceed for the rest of the session. A user
    correction clears it back to null.
    """

    id: str
    conversation_id: str
    confirmed_database_id: str | None
    created_at: datetime
    last_active_at: datetime


class SessionStore(ABC):
    """Abstract store for sessions and append-only message history."""

    @abstractmethod
    async def init_schema(self) -> None:
        """Idempotently create the store's schema; safe to call on every startup."""

    @abstractmethod
    async def create(self, conversation_id: str) -> Session:
        """Create and return a new session for ``conversation_id``."""

    @abstractmethod
    async def get(self, session_id: str) -> Session | None:
        """Return the session, or ``None`` if it does not exist."""

    @abstractmethod
    async def next_seq(self, session_id: str) -> int:
        """Return the sequence number the next appended message should use.

        The caller derives ``seq_start`` from this before running a turn, so that
        a concurrent writer computing the same value collides on insert rather
        than interleaving silently.
        """

    @abstractmethod
    async def append_messages(self, session_id: str, seq_start: int, payloads: list[Any]) -> None:
        """Append serialized messages as rows ``seq_start, seq_start + 1, ...``.

        ``payloads`` is ``to_jsonable_python(result.new_messages())``. Raises
        :class:`SessionConflictError` if any target ``(session_id, seq)`` already
        exists (the concurrent-write race).
        """

    @abstractmethod
    async def load_history(self, session_id: str, limit: int) -> list[ModelMessage]:
        """Return the last ``limit`` messages in chronological order.

        Implementations must not return history that opens with an orphaned
        tool return: if the ``limit`` cuts between a tool call and its return,
        trim forward to the next genuine user turn rather than returning a
        malformed prefix a model provider would reject.
        """

    @abstractmethod
    async def set_confirmed_database(self, session_id: str, database_id: str | None) -> None:
        """Set (or clear, with ``None``) the session's confirmed write target."""

    @abstractmethod
    async def touch(self, session_id: str) -> None:
        """Update ``last_active_at`` to now."""

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """Delete the session and all its messages."""
