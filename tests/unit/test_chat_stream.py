"""The SSE chat route emits tool progress and persists the turn exactly once."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai import Agent, ModelResponse, TextPart, ToolCallPart, UsageLimitExceeded, models
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from webtonotion.agents.capabilities import ProcessHistory
from webtonotion.agents.chat_service import ChatService
from webtonotion.agents.deps import AgentDeps
from webtonotion.agents.session.store import Session
from webtonotion.api.chat import router as chat_router
from webtonotion.config.settings import Settings
from webtonotion.dependencies import get_chat_service
from webtonotion.exceptions import LLMError

models.ALLOW_MODEL_REQUESTS = False


def make_settings() -> Settings:
    return Settings(openrouter_api_key="test-key")


def make_session() -> Session:
    now = datetime.now()
    return Session(
        id="s1",
        conversation_id="c1",
        confirmed_database_id=None,
        created_at=now,
        last_active_at=now,
    )


def make_store() -> MagicMock:
    store = MagicMock()
    store.create = AsyncMock(return_value=make_session())
    store.get = AsyncMock(return_value=make_session())
    store.load_history = AsyncMock(return_value=[])
    store.next_seq = AsyncMock(return_value=0)
    store.append_messages = AsyncMock(return_value=None)
    store.touch = AsyncMock(return_value=None)
    store.set_confirmed_database = AsyncMock(return_value=None)
    return store


def script_one_tool_then_reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    if len(messages) == 1:
        return ModelResponse(
            parts=[ToolCallPart("get_video_metadata", {"url": "https://www.example.com/v"})]
        )
    return ModelResponse(parts=[TextPart("It is a gardening video.")])


async def stream_one_tool_then_reply(messages: list[ModelMessage], info: AgentInfo):
    """Streamed counterpart of ``script_one_tool_then_reply``.

    ``agent.run_stream_events`` always drives the model through its streaming path
    (``Model.request_stream``), so ``FunctionModel`` needs a ``stream_function`` too --
    a non-streaming ``function`` alone is not enough to exercise the SSE route.
    """
    response = script_one_tool_then_reply(messages, info)
    part = response.parts[0]
    if isinstance(part, ToolCallPart):
        yield {0: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args))}
    else:
        yield part.content


def make_service(store) -> ChatService:
    settings = make_settings()
    agent: Agent[AgentDeps, str] = Agent(
        FunctionModel(script_one_tool_then_reply, stream_function=stream_one_tool_then_reply),
        deps_type=AgentDeps,
        output_type=str,
    )

    async def fake_metadata(ctx, url: str) -> str:
        return "Test Video by Test Author"

    agent.tool(fake_metadata, name="get_video_metadata")

    return ChatService(
        agent=agent,
        store=store,
        notion_service=MagicMock(),
        settings=settings,
        video_service=MagicMock(),
        cache=MagicMock(),
        history=ProcessHistory(),
    )


def build_client(service) -> TestClient:
    app = FastAPI()
    app.include_router(chat_router, prefix="/api/v1")
    app.dependency_overrides[get_chat_service] = lambda: service
    return TestClient(app)


def parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        name, payload = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                payload = json.loads(line[len("data: ") :])
        events.append({"event": name, "data": payload})
    return events


def test_stream_emits_tool_progress_then_a_final_reply():
    store = make_store()
    client = build_client(make_service(store))

    response = client.post(
        "/api/v1/chat/stream",
        json={"message": "what is this?", "conversation_id": "c1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(response.text)
    names = [e["event"] for e in events]

    assert names[0] == "session"
    assert "tool_call" in names
    assert "tool_return" in names
    assert names[-1] == "reply"
    assert events[-1]["data"]["reply"] == "It is a gardening video."


def test_stream_persists_the_turn_exactly_once():
    store = make_store()
    client = build_client(make_service(store))

    client.post(
        "/api/v1/chat/stream",
        json={"message": "what is this?", "conversation_id": "c1"},
    )

    store.append_messages.assert_awaited_once()
    store.touch.assert_awaited_once()


def test_session_event_carries_the_session_id_before_any_work():
    store = make_store()
    client = build_client(make_service(store))

    response = client.post(
        "/api/v1/chat/stream",
        json={"message": "what is this?", "conversation_id": "c1"},
    )

    first = parse_sse(response.text)[0]
    assert first["event"] == "session"
    assert first["data"]["session_id"] == "s1"


def test_reply_carries_usage_for_the_whole_turn():
    """The streamed `reply` event's `usage` must reflect every model request made
    during the turn (here: one tool-call request + one final-reply request), the
    same field the non-streaming route returns."""
    store = make_store()
    client = build_client(make_service(store))

    response = client.post(
        "/api/v1/chat/stream",
        json={"message": "what is this?", "conversation_id": "c1"},
    )

    reply_event = parse_sse(response.text)[-1]
    usage = reply_event["data"]["usage"]
    assert usage["requests"] == 2
    assert usage["total_tokens"] > 0
    assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]


def make_service_streaming_text(store) -> ChatService:
    """A ChatService whose model streams its reply as several text fragments,
    so the SSE route's incremental `text` events can be exercised."""
    settings = make_settings()

    reply_chunks = ["Here's ", "a summary ", "of the video."]

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("".join(reply_chunks))])

    async def stream(messages: list[ModelMessage], info: AgentInfo):
        for chunk in reply_chunks:
            yield chunk

    agent: Agent[AgentDeps, str] = Agent(
        FunctionModel(script, stream_function=stream),
        deps_type=AgentDeps,
        output_type=str,
    )
    return ChatService(
        agent=agent,
        store=store,
        notion_service=MagicMock(),
        settings=settings,
        video_service=MagicMock(),
        cache=MagicMock(),
        history=ProcessHistory(),
    )


def test_stream_emits_incremental_text_events_that_reconstruct_the_reply():
    store = make_store()
    client = build_client(make_service_streaming_text(store))

    response = client.post(
        "/api/v1/chat/stream",
        json={"message": "summarize", "conversation_id": "c1"},
    )

    events = parse_sse(response.text)
    text_events = [e for e in events if e["event"] == "text"]

    assert len(text_events) >= 2  # streamed, not one lump
    assert "".join(e["data"]["content"] for e in text_events) == "Here's a summary of the video."
    assert events[-1]["event"] == "reply"
    assert events[-1]["data"]["reply"] == "Here's a summary of the video."


def make_service_with_failing_tool(store) -> ChatService:
    """A ChatService whose only tool raises UsageLimitExceeded, simulating a
    sub-agent run (summarize/ask_about_video) that hit the shared turn budget."""
    settings = make_settings()

    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("summarize", {"url": "https://example.com/v"})])

    agent: Agent[AgentDeps, str] = Agent(
        FunctionModel(script),
        deps_type=AgentDeps,
        output_type=str,
    )

    async def failing_summarize(ctx, url: str) -> str:
        raise UsageLimitExceeded("total tokens limit exceeded")

    agent.tool(failing_summarize, name="summarize")

    return ChatService(
        agent=agent,
        store=store,
        notion_service=MagicMock(),
        settings=settings,
        video_service=MagicMock(),
        cache=MagicMock(),
        history=ProcessHistory(),
    )


@pytest.mark.asyncio
async def test_a_sub_agent_s_usage_limit_exceeded_becomes_an_llm_error_and_persists_nothing():
    """A UsageLimitExceeded raised inside a tool (standing in for a sub-agent run
    that shares ctx.usage/ctx.usage_limits) must propagate through agent.run and
    surface as LLMError -> 429, not a 500, with the turn left unsaved."""
    store = make_store()
    service = make_service_with_failing_tool(store)

    with pytest.raises(LLMError):
        await service.handle_message(conversation_id="c1", message="summarize this")

    store.append_messages.assert_not_awaited()


def test_a_failing_run_emits_an_error_event_and_persists_nothing():
    store = make_store()
    service = make_service(store)

    def boom(*args, **kwargs):
        """`_run_stream_events` is sync (it returns an async context manager)."""
        raise RuntimeError("model exploded")

    with patch.object(service, "_run_stream_events", new=boom):
        client = build_client(service)
        response = client.post(
            "/api/v1/chat/stream",
            json={"message": "what is this?", "conversation_id": "c1"},
        )

    names = [e["event"] for e in parse_sse(response.text)]
    assert names[-1] == "error"
    store.append_messages.assert_not_awaited()
