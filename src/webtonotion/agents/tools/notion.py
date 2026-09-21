"""Read-only Notion selection tools plus the write gate.

Four tools back the database-selection flow:

- ``find_databases`` — deterministic pre-filter + ranking over the workspace's
  databases; the model makes the final "which one" judgement.
- ``inspect_schema`` — property names, types, and select options for one database.
- ``confirm_database`` — flips the session's write gate; its own tool so history
  shows exactly which turn granted the write.
- ``save_to_notion`` — enforces the write gate, then runs the real write. It reads
  the confirmed database id off the session and refuses otherwise, returning a
  structured value rather than raising, never trusting the model's own claim that a
  database was confirmed. Once the gate is open it delegates to
  :mod:`webtonotion.agents.writer` to build the page content and create the page.
"""

from __future__ import annotations

from typing import Any, Union

from pydantic_ai import RunContext

from webtonotion.agents.deps import AgentDeps
from webtonotion.agents.errors import RECOVERABLE_VIDEO_ERRORS
from webtonotion.agents.writer import build_page_content, get_database_schema, write_video_page
from webtonotion.config.logging import get_logger
from webtonotion.exceptions import NotionAPIError, NotionAuthenticationError, NotionRateLimitError
from webtonotion.models.chat import (
    DatabaseCandidate,
    SaveResult,
    SchemaInfo,
    ToolError,
    WriteBlocked,
)

logger = get_logger(__name__)

# Notion property types that carry a fixed set of named options.
_OPTION_PROPERTY_TYPES = frozenset({"select", "multi_select", "status"})

# How many property names to surface as "key properties" on a candidate.
_MAX_KEY_PROPERTIES = 4


def _title_property_name(properties: dict[str, Any]) -> str | None:
    """Return the name of the database's ``title`` property, or ``None``."""
    for name, spec in properties.items():
        if isinstance(spec, dict) and spec.get("type") == "title":
            return name
    return None


def _key_property_names(properties: dict[str, Any], title_name: str) -> list[str]:
    """A few distinguishing property names, title first."""
    names = [title_name]
    for name in properties:
        if name != title_name:
            names.append(name)
        if len(names) >= _MAX_KEY_PROPERTIES:
            break
    return names


async def find_databases(ctx: RunContext[AgentDeps], hint: str) -> list[DatabaseCandidate]:
    """Find candidate databases to write to, ranked by relevance to ``hint``.

    Deterministic pre-filter: databases without a ``title`` property are dropped
    (a page cannot be created without one). Ranking is a case-insensitive name
    match — databases whose name contains the hint sort first — leaving the final
    "which one" judgement to the model.
    """
    databases = await ctx.deps.notion_service.get_databases()

    candidates: list[DatabaseCandidate] = []
    for database in databases:
        properties = database.properties or {}
        title_name = _title_property_name(properties)
        if title_name is None:
            continue
        candidates.append(
            DatabaseCandidate(
                id=database.id,
                name=database.name,
                key_properties=_key_property_names(properties, title_name),
            )
        )

    needle = hint.strip().lower()
    if needle:
        # Stable partition: name-matches keep their relative order, then the rest.
        candidates.sort(key=lambda c: needle not in c.name.lower())

    return candidates


async def inspect_schema(ctx: RunContext[AgentDeps], database_id: str) -> SchemaInfo:
    """Return the property names, types, and select options of one database.

    The schema is cached (see :func:`webtonotion.agents.writer.get_database_schema`),
    so a later ``save_to_notion`` call for the same database in this session reuses
    it instead of re-fetching from Notion.
    """
    properties = await get_database_schema(
        notion_service=ctx.deps.notion_service, cache=ctx.deps.cache, database_id=database_id
    )

    prop_types: dict[str, str] = {}
    select_options: dict[str, list[str]] = {}

    for name, spec in properties.items():
        if not isinstance(spec, dict):
            continue
        prop_type = spec.get("type", "")
        prop_types[name] = prop_type
        if prop_type in _OPTION_PROPERTY_TYPES:
            config = spec.get(prop_type) or {}
            options = config.get("options", []) if isinstance(config, dict) else []
            select_options[name] = [
                opt["name"] for opt in options if isinstance(opt, dict) and "name" in opt
            ]

    return SchemaInfo(
        database_id=database_id,
        properties=prop_types,
        select_options=select_options,
    )


async def confirm_database(ctx: RunContext[AgentDeps], database_id: str) -> str:
    """Confirm ``database_id`` as the session's write target.

    Persists the choice through the store and updates the in-memory session so the
    same run sees the gate open immediately. This is its own tool so conversation
    history records precisely which turn granted the write.

    Nothing here verifies that a genuine user turn asked for this confirmation —
    that is currently the orchestrator system prompt's responsibility, not a
    mechanical guarantee. See the module docstring.
    """
    await ctx.deps.store.set_confirmed_database(ctx.deps.session.id, database_id)
    ctx.deps.session.confirmed_database_id = database_id
    return f"Confirmed database {database_id} as the write target for this session."


async def save_to_notion(
    ctx: RunContext[AgentDeps], url: str, database_id: str
) -> Union[SaveResult, WriteBlocked, ToolError]:
    """Save the video at ``url`` to the confirmed Notion database.

    The gate is a single column, ``session.confirmed_database_id``. If it is unset,
    or does not match the requested ``database_id``, the write is refused with a
    structured :class:`WriteBlocked` (never an exception, so the agent can recover
    by proposing databases and asking the user), regardless of what the model
    claims. See the module docstring for what this does and does not guarantee
    about how the column got set.

    Once the gate is open, this builds the bounded page content from the video
    pipeline and runs the shared writer (:func:`webtonotion.agents.writer.write_video_page`)
    to create the page, returning a :class:`SaveResult`. A video that cannot be
    prepared or a Notion rejection comes back as a :class:`ToolError` so the agent
    can relay it; an auth failure and ``UsageLimitExceeded`` propagate.
    """
    confirmed = ctx.deps.session.confirmed_database_id

    if confirmed is None:
        return WriteBlocked(
            reason=(
                "No database is confirmed for this session. Propose a target with "
                "find_databases and ask the user to confirm before saving."
            ),
            candidates=[],
        )

    if confirmed != database_id:
        return WriteBlocked(
            reason=(
                f"The confirmed database is '{confirmed}', not '{database_id}'. "
                "Confirm the requested database first, or save to the confirmed one."
            ),
            candidates=[],
        )

    try:
        content = await build_page_content(video_service=ctx.deps.video_service, url=url)
        return await write_video_page(
            notion_service=ctx.deps.notion_service,
            settings=ctx.deps.settings,
            database_id=database_id,
            content=content,
            cache=ctx.deps.cache,
            usage=ctx.usage,
            usage_limits=ctx.usage_limits,
        )
    except RECOVERABLE_VIDEO_ERRORS as e:
        logger.warning(f"save_to_notion could not prepare {url}: {e}")
        return ToolError(reason="Could not prepare this video for saving.", detail=str(e))
    except NotionAuthenticationError:
        raise
    except (NotionAPIError, NotionRateLimitError) as e:
        logger.warning(f"save_to_notion: Notion rejected the write for {url}: {e}")
        return ToolError(reason="Notion rejected the write.", detail=str(e))
