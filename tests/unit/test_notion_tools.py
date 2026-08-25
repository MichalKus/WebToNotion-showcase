"""Unit tests for the Notion agent tools.

Tests find_databases and inspect_schema tools in webtonotion.agents.tools.notion.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from webtonotion.agents.deps import AgentDeps
from webtonotion.agents.session.store import Session
from webtonotion.agents.tools.notion import find_databases, inspect_schema
from webtonotion.config.settings import settings
from webtonotion.models.notion import NotionDatabase


def _make_session() -> Session:
    now = datetime.now(timezone.utc)
    return Session(
        id="s1",
        conversation_id="c1",
        confirmed_database_id=None,
        created_at=now,
        last_active_at=now,
    )


@pytest.mark.asyncio
async def test_find_databases_filters_and_ranks() -> None:
    now = datetime.now(timezone.utc)
    db_no_title = NotionDatabase(
        id="db_no_title",
        name="No Title DB",
        properties={"Description": {"type": "rich_text"}},
        created_time=now,
        last_edited_time=now,
        url="https://notion.so/db_no_title",
    )
    db_other = NotionDatabase(
        id="db_other",
        name="Other Database",
        properties={"Name": {"type": "title"}, "Tags": {"type": "multi_select"}},
        created_time=now,
        last_edited_time=now,
        url="https://notion.so/db_other",
    )
    db_match = NotionDatabase(
        id="db_match",
        name="Video Library",
        properties={"Title": {"type": "title"}, "URL": {"type": "url"}},
        created_time=now,
        last_edited_time=now,
        url="https://notion.so/db_match",
    )

    mock_notion_service = AsyncMock()
    mock_notion_service.get_databases.return_value = [db_no_title, db_other, db_match]

    deps = AgentDeps(
        notion_service=mock_notion_service,
        session=_make_session(),
        store=AsyncMock(),
        settings=settings,
    )
    ctx: RunContext[AgentDeps] = RunContext(deps=deps, model=TestModel(), usage=RunUsage())

    # Hint matches "video"
    candidates = await find_databases(ctx, hint="video")

    # db_no_title should be excluded
    assert len(candidates) == 2
    # db_match should be ranked first because its name contains "video"
    assert candidates[0].id == "db_match"
    assert candidates[0].name == "Video Library"
    assert "Title" in candidates[0].key_properties
    assert candidates[1].id == "db_other"


@pytest.mark.asyncio
async def test_inspect_schema_extracts_types_and_options() -> None:
    mock_notion_service = AsyncMock()
    mock_notion_service.get_database_properties.return_value = {
        "Name": {"type": "title"},
        "Status": {
            "type": "status",
            "status": {
                "options": [
                    {"id": "1", "name": "To Watch"},
                    {"id": "2", "name": "Watched"},
                ]
            },
        },
        "Category": {
            "type": "select",
            "select": {
                "options": [
                    {"id": "c1", "name": "Tech"},
                    {"id": "c2", "name": "Cooking"},
                ]
            },
        },
        "URL": {"type": "url"},
    }

    deps = AgentDeps(
        notion_service=mock_notion_service,
        session=_make_session(),
        store=AsyncMock(),
        settings=settings,
    )
    ctx: RunContext[AgentDeps] = RunContext(deps=deps, model=TestModel(), usage=RunUsage())

    schema_info = await inspect_schema(ctx, database_id="db1")

    assert schema_info.database_id == "db1"
    assert schema_info.properties["Name"] == "title"
    assert schema_info.properties["Status"] == "status"
    assert schema_info.properties["Category"] == "select"
    assert schema_info.properties["URL"] == "url"
    assert schema_info.select_options["Status"] == ["To Watch", "Watched"]
    assert schema_info.select_options["Category"] == ["Tech", "Cooking"]
