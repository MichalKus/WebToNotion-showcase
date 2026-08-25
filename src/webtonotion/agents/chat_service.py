"""Chat orchestration service.

``ChatService`` runs one conversation turn: it loads the session's history tail,
runs the orchestrator agent with that history and per-run dependencies, persists
the new messages, and returns the reply. Both chat POST routes call
:meth:`handle_message`; they are two serializations of one implementation.

The reply also carries a :class:`TraceStep` list built from ``result.new_messages()``
for just this turn — reasoning (when ``settings.agent_thinking_level`` enables it),
tool calls, tool returns, and any intermediate text — so a client can see why the
agent acted without querying Logfire or replaying the full session history.

It lives in the ``agents`` layer (not ``services``) because it drives the
orchestrator and session store, which live here — ``services`` must never import
from ``agents``. The service is transport-agnostic: it raises domain errors
(:class:`SessionNotFoundError`, :class:`SessionConflictError`, :class:`LLMError`
on a run that exceeds its request budget) and never ``HTTPException``; the API
layer maps those to status codes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai import UsageLimitExceeded, UsageLimits
from pydantic_ai.messages import (
    BaseToolCallPart,
    BaseToolReturnPart,
    ModelMessage,
    TextPart,
    ThinkingPart,
)
from pydantic_core import to_jsonable_python

from webtonotion.agents.capabilities import ProcessHistory
from webtonotion.agents.deps import AgentDeps
from webtonotion.agents.session.store import (
    Session,
    SessionConflictError,
    SessionNotFoundError,
    SessionStore,
)
from webtonotion.exceptions import LLMError
from webtonotion.models.chat import ChatReply, TraceStep

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from webtonotion.config.settings import Settings
    from webtonotion.services.notion_service import NotionService


class ChatService:
    """Drives one orchestrator turn and persists it to the session store."""

    def __init__(
        self,
        agent: "Agent[AgentDeps, str]",
        store: SessionStore,
        notion_service: "NotionService",
        settings: "Settings",
        history: ProcessHistory | None = None,
    ) -> None:
        self._agent = agent
        self._store = store
        self._notion_service = notion_service
        self._settings = settings
        self._history = history or ProcessHistory()

    async def handle_message(
        self, conversation_id: str, message: str, session_id: str | None = None
    ) -> ChatReply:
        """Run one turn and return the assistant's reply.

        Loads the history tail, runs the agent bounded by ``UsageLimits``, appends
        the new messages, and touches the session. A concurrent turn on the same
        session raises :class:`SessionConflictError` (mapped to 409); an unknown
        ``session_id`` raises :class:`SessionNotFoundError` (mapped to 404); a run
        that exceeds ``agent_max_requests`` raises :class:`LLMError` (mapped to 429)
        rather than the default 500 an unhandled ``UsageLimitExceeded`` would produce.
        The turn is not persisted in that case — the run stopped mid-loop with no
        well-formed reply to save, and any tool calls it made are the model's own
        (nothing user-confirmed) since it hit the request cap before finishing.
        """
        session = await self._resolve_session(conversation_id, session_id)
        gate_before_run = session.confirmed_database_id

        history = await self._store.load_history(session.id, self._history.message_limit)
        seq_start = await self._store.next_seq(session.id)

        deps = AgentDeps(
            notion_service=self._notion_service,
            session=session,
            store=self._store,
            settings=self._settings,
        )

        try:
            result = await self._agent.run(
                message,
                message_history=history,
                deps=deps,
                usage_limits=UsageLimits(request_limit=self._settings.agent_max_requests),
            )
        except UsageLimitExceeded as exc:
            raise LLMError(
                f"This turn exceeded the {self._settings.agent_max_requests}-request budget "
                "for a single conversation turn and was not saved. Try a more direct request."
            ) from exc

        new_messages = result.new_messages()
        payloads = to_jsonable_python(new_messages)
        try:
            await self._store.append_messages(session.id, seq_start, payloads)
        except SessionConflictError:
            # This turn lost the race and will never appear in persisted history.
            # If it flipped the write gate (confirm_database), that decision has
            # no audit trail and must not survive a rejected turn.
            if session.confirmed_database_id != gate_before_run:
                await self._store.set_confirmed_database(session.id, gate_before_run)
            raise
        await self._store.touch(session.id)

        return ChatReply(
            session_id=session.id,
            reply=result.output,
            confirmed_database_id=session.confirmed_database_id,
            trace=_build_trace(new_messages),
        )

    async def get_history(self, session_id: str) -> list[Any]:
        """Return the full serialized message history for a UI replay.

        Raises :class:`SessionNotFoundError` if the session does not exist.
        """
        session = await self._store.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        messages = await self._store.load_history(session_id, limit=_REPLAY_LIMIT)
        payload: list[Any] = to_jsonable_python(messages)
        return payload

    async def end_session(self, session_id: str) -> None:
        """Delete a session and its history (idempotent)."""
        await self._store.delete(session_id)

    async def _resolve_session(self, conversation_id: str, session_id: str | None) -> Session:
        """Return the referenced session, or create a fresh one when none is given."""
        if session_id is None:
            return await self._store.create(conversation_id)
        session = await self._store.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session


def _build_trace(messages: list[ModelMessage]) -> list[TraceStep]:
    """Flatten one turn's messages into a compact, chronological trace.

    Empty thinking/text parts are skipped (some providers emit them as
    placeholders). Tool return content is made JSON-safe the same way session
    persistence is, falling back to ``str()`` for anything that resists it.
    """
    steps: list[TraceStep] = []
    for message in messages:
        for part in message.parts:
            if isinstance(part, ThinkingPart):
                if part.content:
                    steps.append(TraceStep(kind="thinking", content=part.content))
            elif isinstance(part, BaseToolCallPart):
                steps.append(TraceStep(kind="tool_call", tool=part.tool_name, args=part.args))
            elif isinstance(part, BaseToolReturnPart):
                steps.append(
                    TraceStep(
                        kind="tool_return",
                        tool=part.tool_name,
                        content=_jsonable_or_str(part.content),
                    )
                )
            elif isinstance(part, TextPart):
                if part.content:
                    steps.append(TraceStep(kind="text", content=part.content))
    return steps


def _jsonable_or_str(value: Any) -> Any:
    """Best-effort JSON-safe conversion; falls back to ``str()``."""
    try:
        return to_jsonable_python(value)
    except Exception:
        return str(value)


# Upper bound on messages returned by a history replay. Turns are cheap (tool
# results are small handles), so this comfortably covers a full conversation.
_REPLAY_LIMIT = 1000
