"""Tests for the ``save_to_notion`` write wiring (gate OPEN paths).

The gate-CLOSED behaviour is covered by ``test_write_gate.py``; here the session's
``confirmed_database_id`` matches the requested ``database_id`` so control reaches
the shared writer, which is stubbed out. One case re-checks that a mismatched gate
still short-circuits to ``WriteBlocked`` without touching the writer.
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic_ai import RunContext, models
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from webtonotion.agents.deps import AgentDeps
from webtonotion.agents.session.store import Session, SessionStore
from webtonotion.agents.tools import notion as notion_tools
from webtonotion.agents.tools.notion import save_to_notion
from webtonotion.config.settings import settings
from webtonotion.exceptions import (
    ContentProcessingError,
    NotionAPIError,
    NotionAuthenticationError,
    VideoScrapingError,
)
from webtonotion.models.chat import SaveResult, ToolError, WriteBlocked
from webtonotion.models.video import VideoPageContent

models.ALLOW_MODEL_REQUESTS = False


class FakeSessionStore(SessionStore):
    """In-memory store that records any confirmed-database writes."""

    def __init__(self) -> None:
        self.set_calls: list[tuple[str, str | None]] = []
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
        self.set_calls.append((session_id, database_id))
        self.confirmed[session_id] = database_id

    async def touch(self, session_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def delete(self, session_id: str) -> None:  # pragma: no cover
        raise NotImplementedError


def _session_with_gate(gate: str | None) -> Session:
    now = datetime.now(timezone.utc)
    return Session(
        id="s1",
        conversation_id="c1",
        confirmed_database_id=gate,
        created_at=now,
        last_active_at=now,
    )


def _deps(session: Session) -> AgentDeps:
    return AgentDeps(
        notion_service=MagicMock(),
        session=session,
        store=FakeSessionStore(),
        settings=settings,
        video_service=MagicMock(),
        cache=MagicMock(),
    )


def _ctx(deps: AgentDeps) -> RunContext[AgentDeps]:
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage())


def _page_content() -> VideoPageContent:
    return VideoPageContent(
        url="https://example.com/v",
        title="A video",
        author="Someone",
        description="",
        duration=None,
        published_at=None,
        platform="youtube",
        language=None,
        summary="",
        transcript_excerpt="",
    )


def _save_result() -> SaveResult:
    return SaveResult(
        page_id="page-1",
        page_url="https://notion.so/page-1",
        database_id="db-1",
        title="A video",
    )


@pytest.fixture(autouse=True)
def _stub_build_page_content(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_build(*, video_service: Any, url: str) -> VideoPageContent:
        return _page_content()

    monkeypatch.setattr(notion_tools, "build_page_content", fake_build)


@pytest.mark.asyncio
async def test_gate_open_returns_save_result(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _save_result()
    seen_kwargs: dict[str, Any] = {}

    async def fake_write(**kwargs: Any) -> SaveResult:
        seen_kwargs.update(kwargs)
        return result

    monkeypatch.setattr(notion_tools, "write_video_page", fake_write)

    deps = _deps(_session_with_gate("db-1"))
    out = await save_to_notion(_ctx(deps), url="https://example.com/v", database_id="db-1")

    assert out is result
    # The session's shared artifact cache is forwarded so write_video_page can reuse
    # a schema already fetched by inspect_schema earlier in the session.
    assert seen_kwargs["cache"] is deps.cache


@pytest.mark.asyncio
async def test_video_scraping_error_becomes_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_write(**kwargs: Any) -> SaveResult:
        raise VideoScrapingError("no audio track")

    monkeypatch.setattr(notion_tools, "write_video_page", fake_write)

    deps = _deps(_session_with_gate("db-1"))
    out = await save_to_notion(_ctx(deps), url="https://example.com/v", database_id="db-1")

    assert isinstance(out, ToolError)
    assert "prepar" in out.reason.lower()


@pytest.mark.asyncio
async def test_content_processing_error_becomes_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_write(**kwargs: Any) -> SaveResult:
        raise ContentProcessingError("Notion mapping failed: boom")

    monkeypatch.setattr(notion_tools, "write_video_page", fake_write)

    deps = _deps(_session_with_gate("db-1"))
    out = await save_to_notion(_ctx(deps), url="https://example.com/v", database_id="db-1")

    assert isinstance(out, ToolError)


@pytest.mark.asyncio
async def test_notion_authentication_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_write(**kwargs: Any) -> SaveResult:
        raise NotionAuthenticationError("bad token")

    monkeypatch.setattr(notion_tools, "write_video_page", fake_write)

    deps = _deps(_session_with_gate("db-1"))
    with pytest.raises(NotionAuthenticationError):
        await save_to_notion(_ctx(deps), url="https://example.com/v", database_id="db-1")


@pytest.mark.asyncio
async def test_notion_api_error_becomes_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_write(**kwargs: Any) -> SaveResult:
        raise NotionAPIError("422 validation_error")

    monkeypatch.setattr(notion_tools, "write_video_page", fake_write)

    deps = _deps(_session_with_gate("db-1"))
    out = await save_to_notion(_ctx(deps), url="https://example.com/v", database_id="db-1")

    assert isinstance(out, ToolError)
    assert "notion rejected" in out.reason.lower()


@pytest.mark.asyncio
async def test_gate_mismatch_blocks_without_calling_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fake_write(**kwargs: Any) -> SaveResult:
        nonlocal called
        called = True
        return _save_result()

    monkeypatch.setattr(notion_tools, "write_video_page", fake_write)

    deps = _deps(_session_with_gate("a"))
    out = await save_to_notion(_ctx(deps), url="https://example.com/v", database_id="b")

    assert isinstance(out, WriteBlocked)
    assert called is False
