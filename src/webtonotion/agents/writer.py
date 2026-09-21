"""The one shared Notion write path.

Both ``POST /api/v1/process/url`` and the ``save_to_notion`` orchestrator tool go
through :func:`write_video_page`: it builds the mapper prompt, runs the Notion
mapper agent against the target database schema, filters empty property values,
and creates the page. :func:`build_page_content` assembles the bounded
:class:`VideoPageContent` DTO the mapper receives from the video pipeline.

This module lives in ``agents/`` rather than ``services/`` because it depends on
both ``services/notion_service`` and a PydanticAI agent, and ``services/`` must
never import ``agents/``. It may import from ``services/``; it must not import
from ``api/``.

Error policy for :func:`write_video_page`:

* ``create_page`` failures propagate untouched (``NotionAuthenticationError`` /
  ``NotionRateLimitError`` / ``NotionAPIError``) -- the caller maps them to HTTP
  status codes.
* ``UsageLimitExceeded`` and an auth ``ModelHTTPError`` (401/403) propagate.
* Any other mapper failure (``UnexpectedModelBehavior``, a transient
  ``ModelHTTPError``, ``ModelRetry`` exhaustion, or an unexpected error inside the
  run) is wrapped as ``ContentProcessingError("Notion mapping failed: ...")``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded
from pydantic_ai.usage import RunUsage, UsageLimits

from webtonotion.agents.errors import FATAL_AUTH_HTTP_STATUS
from webtonotion.config.logging import get_logger
from webtonotion.exceptions import ContentProcessingError, VideoScrapingError
from webtonotion.models.chat import SaveResult
from webtonotion.models.video import VideoPageContent
from webtonotion.services.analysis.notion_mapper import MapperDependencies, build_mapper_agent

if TYPE_CHECKING:
    from webtonotion.config.settings import Settings
    from webtonotion.services.notion_service import NotionService
    from webtonotion.services.storage.file_cache import FileCacheService
    from webtonotion.services.video_scraping_service import VideoScrapingService

logger = get_logger(__name__)

_TRANSCRIPT_EXCERPT_CHARS = 4000
"""How much transcript text the mapper prompt carries -- generous vs the old 500."""

_CACHED_SUMMARY_KEY = "concise:medium"
"""Preferred cached summary variant (``{style}:{length}``) for the page body."""

_SCHEMA_ARTIFACT = "schema"
"""Cache artifact name for a fetched database schema, keyed by database_id."""


async def build_page_content(
    *, video_service: "VideoScrapingService", url: str
) -> VideoPageContent:
    """Assemble the bounded DTO the Notion mapper receives for ``url``.

    ``url`` must be a supported video URL -- checked here rather than left to each
    caller, so every caller (``POST /process/url``, the ``save_to_notion`` chat tool,
    and any future one) rejects a non-video URL the same way instead of falling
    through to whatever generic error the extractor happens to raise.

    ``fetch_metadata`` is required -- a ``VideoScrapingError`` from it propagates.
    ``fetch_transcript`` is tolerant: a no-audio ``VideoScrapingError`` is logged
    and simply yields an empty excerpt, so a page is still created from metadata.
    The summary is a cached ``concise:medium`` variant when present, else any
    cached variant, else empty.

    Raises:
        VideoScrapingError: ``url`` is not a supported video URL, or metadata
            extraction failed.
    """
    if not await video_service.is_video_url(url):
        raise VideoScrapingError(f"Not a supported video URL: {url}")

    data = await video_service.fetch_metadata(url)

    transcript_excerpt = ""
    language: str | None = None
    try:
        stored = await video_service.fetch_transcript(url)
        transcript_excerpt = stored.text[:_TRANSCRIPT_EXCERPT_CHARS]
        language = stored.language
    except VideoScrapingError as e:
        logger.warning(f"No transcript for {url}, creating page from metadata only: {e}")

    summaries = data.summaries or {}
    summary = (
        summaries[_CACHED_SUMMARY_KEY]
        if _CACHED_SUMMARY_KEY in summaries
        else next(iter(summaries.values()), "")
    )

    return VideoPageContent(
        url=url,
        title=data.title,
        author=data.author,
        description=data.description,
        duration=data.duration,
        published_at=data.published_at,
        platform=str(data.metadata.get("platform", "unknown")),
        language=language,
        summary=summary,
        transcript_excerpt=transcript_excerpt,
    )


def build_mapper_prompt(content: VideoPageContent) -> str:
    """Render the descriptive prompt the Notion mapper agent sees.

    Modelled on the pre-refactor prompt that used to be assembled inline inside
    ``NotionService`` (title/author/URL/description/duration/published) minus the
    dropped topics/sentiment/locations/metadata, plus the AI summary and a
    transcript excerpt.
    """
    return (
        "Map this video content to the Notion database schema:\n"
        f"Video Title: {content.title}\n"
        f"Video Author: {content.author}\n"
        f"Video URL: {content.url}\n"
        f"Video Description: {content.description}\n"
        f"Video Duration: {content.duration} seconds\n"
        f"Published At: {content.published_at}\n"
        f"Platform: {content.platform}\n"
        f"Language: {content.language}\n"
        f"Summary: {content.summary}\n"
        f"Transcript Excerpt: {content.transcript_excerpt}\n"
        "\n"
        "Please analyze this video content and create a Notion page payload that "
        "maps all relevant information to the provided database schema."
    )


async def get_database_schema(
    *,
    notion_service: "NotionService",
    cache: "FileCacheService",
    database_id: str,
) -> dict[str, Any]:
    """Return ``database_id``'s property schema, from the shared cache when present.

    Backs both the ``inspect_schema`` tool and :func:`write_video_page`, so a schema
    fetched to describe a database to the user is not re-fetched moments later to
    write to it -- the schema rarely changes within a session, and Notion rate-limits
    this to 3 requests/second. Cached under ``database_id`` in the same process-wide
    :class:`~webtonotion.services.storage.file_cache.FileCacheService` the video
    pipeline uses, expiring on ``cache_expiration`` like any other non-metadata
    artifact.
    """
    cached = await cache.get_artifact(database_id, _SCHEMA_ARTIFACT)
    if cached is not None:
        return cached

    schema = await notion_service.get_database_properties(database_id)
    await cache.put_artifact(database_id, _SCHEMA_ARTIFACT, schema)
    return schema


async def write_video_page(
    *,
    notion_service: "NotionService",
    settings: "Settings",
    database_id: str,
    content: VideoPageContent,
    db_schema: dict[str, Any] | None = None,
    cache: "FileCacheService | None" = None,
    usage: RunUsage | None = None,
    usage_limits: UsageLimits | None = None,
) -> SaveResult:
    """Map ``content`` onto ``database_id``'s schema and create the Notion page.

    Args:
        notion_service: Notion API client wrapper.
        settings: Application settings (selects the mapper model).
        database_id: Target Notion database id.
        content: The bounded DTO to map.
        db_schema: Pre-fetched database schema, used as-is when given.
        cache: Shared artifact cache. When ``db_schema`` is omitted, the schema is
            served through :func:`get_database_schema` (cache-or-fetch) if a cache is
            given, else fetched directly via ``notion_service.get_database_properties``.
        usage: Shared usage accumulator to charge the mapper run against.
        usage_limits: Usage limits to enforce on the mapper run.

    Returns:
        SaveResult describing the created page.

    Raises:
        ContentProcessingError: The mapper run failed (non-auth).
        NotionAuthenticationError / NotionRateLimitError / NotionAPIError: from
            ``create_page``, propagated untouched.
        UsageLimitExceeded: The mapper run exceeded ``usage_limits``.
        ModelHTTPError: An auth (401/403) error from the mapper model.
    """
    if db_schema is not None:
        schema = db_schema
    elif cache is not None:
        schema = await get_database_schema(
            notion_service=notion_service, cache=cache, database_id=database_id
        )
    else:
        schema = await notion_service.get_database_properties(database_id)

    prompt = build_mapper_prompt(content)
    deps = MapperDependencies(schema=schema, database_id=database_id)

    try:
        result = await build_mapper_agent(settings).run(
            prompt,
            deps=deps,
            usage=usage,
            usage_limits=usage_limits,
        )
    except UsageLimitExceeded:
        raise
    except ModelHTTPError as e:
        if e.status_code in FATAL_AUTH_HTTP_STATUS:
            raise
        raise ContentProcessingError(f"Notion mapping failed: {e}") from e
    except Exception as e:
        # UnexpectedModelBehavior (incl. ModelRetry exhaustion), a transient
        # ModelHTTPError, and any other failure inside the run collapse to a
        # single, honest processing error. create_page is deliberately OUTSIDE
        # this block so its NotionError subclasses are never swallowed here.
        raise ContentProcessingError(f"Notion mapping failed: {e}") from e

    payload = result.output
    # Drop empty property values: Pydantic's exclude_none can leave empty dicts
    # for optional 'select'/'date' fields, which Notion rejects.
    properties = {k: v for k, v in payload.properties.items() if v}

    resp = await notion_service.create_page(
        database_id=database_id,
        properties=properties,
        children=payload.children,
    )

    return SaveResult(
        page_id=resp.id,
        page_url=resp.url,
        database_id=database_id,
        title=content.title,
    )
