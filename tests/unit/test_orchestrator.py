"""Orchestrator tool-sequence tests.

Drives the orchestrator under a scripted ``FunctionModel`` (no live model) and
asserts, via ``capture_run_messages``, that the selection flow runs the tools in
order: find_databases -> inspect_schema -> confirm_database -> final reply.
"""

from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic_ai import ModelResponse, TextPart, ToolCallPart, capture_run_messages, models
from pydantic_ai.models.function import AgentInfo, FunctionModel

from webtonotion.agents.deps import AgentDeps
from webtonotion.agents.orchestrator import build_orchestrator
from webtonotion.agents.session.store import Session, SessionStore
from webtonotion.config.settings import settings
from webtonotion.models.notion import NotionDatabase

models.ALLOW_MODEL_REQUESTS = False


class FakeSessionStore(SessionStore):
    """In-memory ``SessionStore`` recording the confirmed database id."""

    def __init__(self) -> None:
        self.confirmed: dict[str, str | None] = {}

    async def init_schema(self) -> None:  # pragma: no cover
        raise NotImplementedError

    async def create(self, conversation_id: str) -> Session:  # pragma: no cover
        raise NotImplementedError

    async def get(self, session_id: str) -> Session | None:  # pragma: no cover
        raise NotImplementedError

    async def next_seq(self, session_id: str) -> int:  # pragma: no cover
        raise NotImplementedError

    async def append_messages(
        self, session_id: str, seq_start: int, payloads: list[Any]
    ) -> None:  # pragma: no cover
        raise NotImplementedError

    async def load_history(self, session_id: str, limit: int) -> list[Any]:  # pragma: no cover
        raise NotImplementedError

    async def set_confirmed_database(self, session_id: str, database_id: str | None) -> None:
        self.confirmed[session_id] = database_id

    async def touch(self, session_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def delete(self, session_id: str) -> None:  # pragma: no cover
        raise NotImplementedError


class FakeNotionService:
    """Minimal fake exposing the two read methods the tools call."""

    def __init__(self, databases: list[NotionDatabase], properties: dict[str, Any]) -> None:
        self._databases = databases
        self._properties = properties

    async def get_databases(self) -> list[NotionDatabase]:
        return self._databases

    async def get_database_properties(self, database_id: str) -> dict[str, Any]:
        return self._properties


def _make_session() -> Session:
    now = datetime.now(timezone.utc)
    return Session(
        id="s1",
        conversation_id="c1",
        confirmed_database_id=None,
        created_at=now,
        last_active_at=now,
    )


def _make_database() -> NotionDatabase:
    now = datetime.now(timezone.utc)
    return NotionDatabase(
        id="db1",
        name="Video Library",
        properties={
            "Name": {"type": "title"},
            "Status": {"type": "select", "select": {"options": [{"name": "To Watch"}]}},
        },
        created_time=now,
        last_edited_time=now,
        url="https://notion.so/db1",
    )


def _script(messages: list[Any], info: AgentInfo) -> ModelResponse:
    """Emit one tool call per step, then a final text reply."""
    step = len([m for m in messages if isinstance(m, ModelResponse)])
    if step == 0:
        return ModelResponse(parts=[ToolCallPart("find_databases", {"hint": "videos"})])
    if step == 1:
        return ModelResponse(parts=[ToolCallPart("inspect_schema", {"database_id": "db1"})])
    if step == 2:
        return ModelResponse(parts=[ToolCallPart("confirm_database", {"database_id": "db1"})])
    return ModelResponse(parts=[TextPart("Confirmed Video Library as the target.")])


@pytest.mark.asyncio
async def test_orchestrator_runs_selection_tools_in_order() -> None:
    agent = build_orchestrator(settings)
    store = FakeSessionStore()
    session = _make_session()
    deps = AgentDeps(
        notion_service=FakeNotionService([_make_database()], {"Name": {"type": "title"}}),
        session=session,
        store=store,
        settings=settings,
    )

    with capture_run_messages() as captured:
        with agent.override(model=FunctionModel(_script), deps=deps):
            result = await agent.run("Find a database and confirm it")

    tool_calls = [
        part.tool_name
        for message in captured
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]

    assert tool_calls == ["find_databases", "inspect_schema", "confirm_database"]
    assert result.output == "Confirmed Video Library as the target."
    # confirm_database flipped the gate on both the store and the in-memory session.
    assert store.confirmed["s1"] == "db1"
    assert session.confirmed_database_id == "db1"


def test_build_orchestrator_openrouter_reasoning_settings() -> None:
    # Default settings (e.g. medium)
    agent = build_orchestrator(settings)
    assert agent.model_settings is not None
    assert agent.model_settings.get("openrouter_reasoning") == {
        "effort": settings.agent_thinking_level
    }

    # "off" level maps to OpenRouter "none" effort
    off_settings = settings.model_copy(update={"agent_thinking_level": "off"})
    off_agent = build_orchestrator(off_settings)
    assert off_agent.model_settings is not None
    assert off_agent.model_settings.get("openrouter_reasoning") == {"effort": "none"}
