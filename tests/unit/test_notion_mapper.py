"""Unit tests for the Notion Mapper Agent validation logic."""

import os
import subprocess
import sys

import pytest
from pydantic_ai import ModelRetry, RunContext

from webtonotion.models.notion import NotionPagePayload
from webtonotion.services.analysis.notion_mapper import MapperDependencies, validate_notion_payload


def test_notion_mapper_importable_without_openrouter_api_key():
    """Importing this module must not require a real OpenRouter key.

    It previously raised eagerly at module scope when the key was unset,
    which broke test collection in CI (no OPENROUTER_API_KEY secret there)
    even though every real usage mocks the network call and never needs a
    real key to run the unit tests.
    """
    env = os.environ.copy()
    env["OPENROUTER_API_KEY"] = ""
    result = subprocess.run(
        [sys.executable, "-c", "import webtonotion.services.analysis.notion_mapper"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_validate_notion_payload_success():
    """Test validator with a correct payload."""
    deps = MapperDependencies(
        database_id="test_db_123",
        schema={"Name": {"type": "title"}, "Status": {"type": "select"}},
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
        schema={"Name": {"type": "title"}},
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
        schema={"Name": {"type": "title"}},
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
        schema={"Name": {"type": "title"}},
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
