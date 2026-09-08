"""Chat orchestration service.

``ChatService`` runs one conversation turn: it loads the session's history tail,
runs the orchestrator agent with that history and per-run dependencies, persists
the new messages, and returns the reply. Both chat POST routes call
:meth:`handle_message`; they are two serializations of one implementation.

The reply also carries a :class:`TraceStep` list built from ``result.new_messages()``
for just this turn — reasoning (when ``settings.agent_thinking_level`` enables it),
tool calls, tool returns, and any intermediate text — so a client can see why the
agent acted without querying Logfire or replaying the full session history. It also
carries a :class:`UsageSummary` built from ``result.usage``, which reflects the
whole turn: ``summarize``/``ask_about_video`` sub-agent runs share the orchestrator's
``RunContext.usage``, so this is the real cost of the turn, not just the
orchestrator's own requests.

It lives in the ``agents`` layer (not ``services``) because it drives the
orchestrator and session store, which live here — ``services`` must never import
from ``agents``. The service is transport-agnostic: it raises domain errors
(:class:`SessionNotFoundError`, :class:`SessionConflictError`, :class:`LLMError`
on a run that exceeds its request or token budget) and never ``HTTPException``;
the API layer maps those to status codes.

``stream_message`` is the same turn, emitted as it happens: tool-start and tool-end
events, reasoning, and reply text, followed by persistence identical to
``handle_message``. Transcribing a long video takes 30-60 seconds or more, and without
progress events the user sits on a dead spinner. Both entry points share
``_persist_turn`` so there is one persistence path, not two.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncIterator

from pydantic_ai import (
    AgentRunResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    UsageLimitExceeded,
    UsageLimits,
)
from pydantic_ai.messages import (
    BaseToolCallPart,
    BaseToolReturnPart,
    ModelMessage,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
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
from webtonotion.models.chat import ChatReply, TraceStep, UsageSummary

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from webtonotion.config.settings import Settings
    from webtonotion.services.notion_service import NotionService
    from webtonotion.services.storage.file_cache import FileCacheService
    from webtonotion.services.video_scraping_service import VideoScrapingService

logger = logging.getLogger(__name__)


class ChatService:
    """Drives one orchestrator turn and persists it to the session store."""

    def __init__(
        self,
        agent: "Agent[AgentDeps, str]",
        store: SessionStore,
        notion_service: "NotionService",
        settings: "Settings",
        video_service: "VideoScrapingService",
        cache: "FileCacheService",
        history: ProcessHistory | None = None,
    ) -> None:
        self._agent = agent
        self._store = store
        self._notion_service = notion_service
        self._settings = settings
        self._video_service = video_service
        self._cache = cache
        self._history = history or ProcessHistory()

    async def handle_message(
        self, conversation_id: str, message: str, session_id: str | None = None
    ) -> ChatReply:
        """Run one turn and return the assistant's reply.

        Loads the history tail, runs the agent bounded by ``UsageLimits``, appends
        the new messages, and touches the session. A concurrent turn on the same
        session raises :class:`SessionConflictError` (mapped to 409); an unknown
        ``session_id`` raises :class:`SessionNotFoundError` (mapped to 404); a run
        that exceeds the turn's request or token budget raises :class:`LLMError`
        (mapped to 429) rather than the default 500 an unhandled
        ``UsageLimitExceeded`` would produce -- including a ``UsageLimitExceeded``
        raised inside a sub-agent run (``summarize``/``ask_about_video`` share this
        budget via ``ctx.usage``), which propagates up through the tool call the same
        way. The turn is not persisted in that case — the run stopped mid-loop with no
        well-formed reply to save, and any tool calls it made are the model's own
        (nothing user-confirmed) since it hit the cap before finishing.
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
            video_service=self._video_service,
            cache=self._cache,
        )

        try:
            result = await self._agent.run(
                message,
                message_history=history,
                deps=deps,
                usage_limits=self._usage_limits(),
            )
        except UsageLimitExceeded as exc:
            raise LLMError(
                f"This turn exceeded its usage budget ({exc}) and was not saved. "
                "Try a more direct request."
            ) from exc

        return await self._persist_turn(session, gate_before_run, seq_start, result)

    async def stream_message(
        self, conversation_id: str, message: str, session_id: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Run one turn, yielding progress events as they happen.

        Yields ``{"event": name, "data": {...}}`` dicts. The first event is always
        ``session`` so a client can record the session id before any slow work starts;
        the last is ``reply`` on success or ``error`` on failure. A failed run persists
        nothing, exactly as in :meth:`handle_message`.
        """
        session = await self._resolve_session(conversation_id, session_id)
        gate_before_run = session.confirmed_database_id

        yield {"event": "session", "data": {"session_id": session.id}}

        history = await self._store.load_history(session.id, self._history.message_limit)
        seq_start = await self._store.next_seq(session.id)

        deps = AgentDeps(
            notion_service=self._notion_service,
            session=session,
            store=self._store,
            settings=self._settings,
            video_service=self._video_service,
            cache=self._cache,
        )

        result = None
        try:
            async with self._run_stream_events(message, history, deps) as events:
                async for event in events:
                    if isinstance(event, FunctionToolCallEvent):
                        yield {
                            "event": "tool_call",
                            "data": {
                                "tool": event.part.tool_name,
                                "args": _jsonable_or_str(event.part.args),
                            },
                        }
                    elif isinstance(event, FunctionToolResultEvent):
                        # `part` is a ToolReturnPart on success or a RetryPromptPart when
                        # the tool asked the model to try again; both carry `tool_name`,
                        # and a retry's tool_name is optional, hence the getattr.
                        yield {
                            "event": "tool_return",
                            "data": {
                                "tool": getattr(event.part, "tool_name", None),
                                "content": _jsonable_or_str(event.part.content),
                            },
                        }
                    elif isinstance(event, PartStartEvent):
                        # The opening fragment of a part. Most providers send an empty
                        # or tiny start and stream the body as PartDeltaEvent below;
                        # some put the first token here, hence emitting on both.
                        if isinstance(event.part, ThinkingPart) and event.part.content:
                            yield {"event": "thinking", "data": {"content": event.part.content}}
                        elif isinstance(event.part, TextPart) and event.part.content:
                            yield {"event": "text", "data": {"content": event.part.content}}
                    elif isinstance(event, PartDeltaEvent):
                        # The incremental body of a text/thinking part. Without this the
                        # client only ever sees the (usually empty) start above and then
                        # the whole answer at once in the final `reply`.
                        delta = event.delta
                        if isinstance(delta, ThinkingPartDelta) and delta.content_delta:
                            yield {"event": "thinking", "data": {"content": delta.content_delta}}
                        elif isinstance(delta, TextPartDelta) and delta.content_delta:
                            yield {"event": "text", "data": {"content": delta.content_delta}}
                    elif isinstance(event, AgentRunResultEvent):
                        result = event.result
        except UsageLimitExceeded as exc:
            yield {
                "event": "error",
                "data": {
                    "detail": (
                        f"This turn exceeded its usage budget ({exc}) and was not saved. "
                        "Try a more direct request."
                    )
                },
            }
            return
        except Exception as e:  # noqa: BLE001 - reported to the client, not swallowed
            self_log = f"Streaming chat turn failed: {e}"
            logger.error(self_log, exc_info=True)
            yield {"event": "error", "data": {"detail": "The chat turn failed."}}
            return

        if result is None:
            yield {"event": "error", "data": {"detail": "The chat turn produced no reply."}}
            return

        try:
            reply = await self._persist_turn(session, gate_before_run, seq_start, result)
        except SessionConflictError:
            yield {
                "event": "error",
                "data": {"detail": "Concurrent message in this session; the turn was discarded."},
            }
            return

        yield {"event": "reply", "data": reply.model_dump(mode="json")}

    def _run_stream_events(self, message: str, history: list[ModelMessage], deps: AgentDeps) -> Any:
        """Open the agent's event stream for one turn.

        Split out so tests can substitute a failing stream without patching pydantic-ai.
        """
        return self._agent.run_stream_events(
            message,
            message_history=history,
            deps=deps,
            usage_limits=self._usage_limits(),
        )

    def _usage_limits(self) -> UsageLimits:
        """The turn-wide usage budget, shared with sub-agent runs via ``ctx.usage``.

        ``request_limit`` is a runaway-loop bound generous enough to cover map-reduce
        summarization; ``total_tokens_limit`` is the actual cost guard (0 disables it).
        """
        return UsageLimits(
            request_limit=self._settings.agent_max_requests,
            total_tokens_limit=self._settings.agent_max_total_tokens or None,
        )

    async def _persist_turn(
        self,
        session: Session,
        gate_before_run: str | None,
        seq_start: int,
        result: Any,
    ) -> ChatReply:
        """Append a completed run's messages and build the reply.

        Shared by :meth:`handle_message` and :meth:`stream_message` so there is one
        persistence path. On a lost write race the write gate is rolled back: a turn
        that will never appear in persisted history must not leave a
        ``confirm_database`` decision behind with no audit trail.
        """
        new_messages = result.new_messages()
        payloads = to_jsonable_python(new_messages)
        try:
            await self._store.append_messages(session.id, seq_start, payloads)
        except SessionConflictError:
            if session.confirmed_database_id != gate_before_run:
                await self._store.set_confirmed_database(session.id, gate_before_run)
            raise
        await self._store.touch(session.id)

        return ChatReply(
            session_id=session.id,
            reply=result.output,
            confirmed_database_id=session.confirmed_database_id,
            trace=_build_trace(new_messages),
            usage=_build_usage_summary(result.usage),
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


def _build_usage_summary(usage: Any) -> UsageSummary:
    """Convert a ``RunUsage`` into the API-facing :class:`UsageSummary`.

    ``usage`` reflects the whole turn, including any sub-agent runs delegated to
    from ``summarize``/``ask_about_video`` (they share ``ctx.usage``), not just the
    orchestrator's own requests.
    """
    return UsageSummary(
        requests=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        cost=usage.cost,
    )


def _jsonable_or_str(value: Any) -> Any:
    """Best-effort JSON-safe conversion; falls back to ``str()``."""
    try:
        return to_jsonable_python(value)
    except Exception:
        return str(value)


# Upper bound on messages returned by a history replay. Turns are cheap (tool
# results are small handles), so this comfortably covers a full conversation.
_REPLAY_LIMIT = 1000
