"""Unit tests for the Notion Mapper Agent validation logic."""

import pytest
from pydantic_ai import ModelRetry, RunContext

from webtonotion.models.notion import NotionPagePayload
from webtonotion.services.analysis.notion_mapper import (
    MapperDependencies,
    validate_notion_payload,
)


@pytest.mark.asyncio
async def test_validate_notion_payload_success():
    """Test validator with a correct payload."""
    deps = MapperDependencies(
        database_id="test_db_123",
        schema={"properties": {"Name": {"type": "title"}, "Status": {"type": "select"}}},
    )
    ctx = RunContext(deps=deps, model=None, usage=None, prompt="test")

    payload = NotionPagePayload(
        parent={"database_id": "test_db_123"},
        properties={
            "Name": {"title": [{"text": {"content": "Test Video"}}]},
            "Status": {"select": {"name": "Done"}},
        },
        children=[],
    )

    # Should not raise any exception
    result = await validate_notion_payload(ctx, payload)
    assert result == payload


@pytest.mark.asyncio
async def test_validate_notion_payload_wrong_db_id():
    """Test validator with incorrect database ID."""
    deps = MapperDependencies(
        database_id="test_db_123",
        schema={"properties": {"Name": {"type": "title"}}},
    )
    ctx = RunContext(deps=deps, model=None, usage=None, prompt="test")

    payload = NotionPagePayload(
        parent={"database_id": "WRONG_ID"},
        properties={"Name": {"title": []}},
        children=[],
    )

    with pytest.raises(ModelRetry, match="Incorrect database_id"):
        await validate_notion_payload(ctx, payload)


@pytest.mark.asyncio
async def test_validate_notion_payload_missing_property():
    """Test validator with property not in schema."""
    deps = MapperDependencies(
        database_id="test_db_123",
        schema={"properties": {"Name": {"type": "title"}}},
    )
    ctx = RunContext(deps=deps, model=None, usage=None, prompt="test")

    payload = NotionPagePayload(
        parent={"database_id": "test_db_123"},
        properties={
            "Name": {"title": []},
            "NonExistent": {"select": {"name": "X"}},
        },
        children=[],
    )

    with pytest.raises(ModelRetry, match="Property 'NonExistent' does not exist"):
        await validate_notion_payload(ctx, payload)


@pytest.mark.asyncio
async def test_validate_notion_payload_wrong_property_type():
    """Test validator with property format mismatch."""
    deps = MapperDependencies(
        database_id="test_db_123",
        schema={"properties": {"Name": {"type": "title"}}},
    )
    ctx = RunContext(deps=deps, model=None, usage=None, prompt="test")

    # Schema says 'title', but payload uses 'url'
    payload = NotionPagePayload(
        parent={"database_id": "test_db_123"},
        properties={"Name": {"url": "https://..."}},
        children=[],
    )

    with pytest.raises(ModelRetry, match="Expected key 'title'"):
        await validate_notion_payload(ctx, payload)
