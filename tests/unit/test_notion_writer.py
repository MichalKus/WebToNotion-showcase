"""Unit tests for the shared Notion write path in ``webtonotion.agents.writer``.

No live model: the mapper agent is driven by a ``FunctionModel`` via
``build_mapper_agent(settings).override(...)`` and the services are ``AsyncMock``s.
``ExtractionData`` / ``StoredTranscript`` / ``NotionPagePayload`` are built directly
(CLAUDE.md: do not mock Notion payload structures).
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import ModelResponse, TextPart, models
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage, UsageLimits

from webtonotion.agents.writer import (
    _TRANSCRIPT_EXCERPT_CHARS,
    build_mapper_prompt,
    build_page_content,
    get_database_schema,
    write_video_page,
)
from webtonotion.config.settings import Settings
from webtonotion.exceptions import (
    ContentProcessingError,
    NotionAuthenticationError,
    VideoScrapingError,
)
from webtonotion.models.chat import SaveResult
from webtonotion.models.notion import NotionPagePayload
from webtonotion.models.transcript import StoredTranscript, TranscriptSegment
from webtonotion.models.video import VideoPageContent
from webtonotion.services.analysis.notion_mapper import build_mapper_agent
from webtonotion.services.extraction.base import ExtractionData

models.ALLOW_MODEL_REQUESTS = False


def make_settings(**overrides) -> Settings:
    return Settings(openrouter_api_key="test-key", **overrides)


def make_extraction(**overrides) -> ExtractionData:
    base = dict(
        url="https://youtube.com/watch?v=abc",
        title="A Video",
        description="A description",
        author="An Author",
        duration=123.0,
        published_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        metadata={"platform": "youtube"},
        summaries={},
    )
    base.update(overrides)
    return ExtractionData(**base)


def make_transcript(text: str = "hello world transcript") -> StoredTranscript:
    return StoredTranscript(
        text=text,
        language="en",
        duration=20.0,
        segments=[TranscriptSegment(start=0.0, end=20.0, text=text)],
    )


def make_video_service(*, metadata: ExtractionData, transcript=None) -> AsyncMock:
    svc = AsyncMock()
    svc.fetch_metadata.return_value = metadata
    if isinstance(transcript, Exception):
        svc.fetch_transcript.side_effect = transcript
    else:
        svc.fetch_transcript.return_value = transcript
    return svc


# --------------------------------------------------------------------------- #
# build_page_content
# --------------------------------------------------------------------------- #


class TestBuildPageContent:
    @pytest.mark.asyncio
    async def test_happy_path_assembles_metadata_and_transcript(self):
        svc = make_video_service(
            metadata=make_extraction(summaries={"concise:medium": "the cached summary"}),
            transcript=make_transcript("some spoken words"),
        )

        content = await build_page_content(video_service=svc, url="https://youtube.com/watch?v=abc")

        assert isinstance(content, VideoPageContent)
        assert content.title == "A Video"
        assert content.author == "An Author"
        assert content.description == "A description"
        assert content.duration == 123.0
        assert content.platform == "youtube"
        assert content.language == "en"
        assert content.summary == "the cached summary"
        assert content.transcript_excerpt == "some spoken words"

    @pytest.mark.asyncio
    async def test_no_audio_is_tolerated(self):
        svc = make_video_service(
            metadata=make_extraction(summaries={"detailed:long": "only summary"}),
            transcript=VideoScrapingError("no audio track"),
        )

        content = await build_page_content(video_service=svc, url="https://youtube.com/watch?v=abc")

        assert content.transcript_excerpt == ""
        assert content.language is None
        # metadata still present
        assert content.title == "A Video"
        assert content.platform == "youtube"
        # falls back to the only cached summary
        assert content.summary == "only summary"

    @pytest.mark.asyncio
    async def test_fetch_metadata_error_propagates(self):
        svc = AsyncMock()
        svc.fetch_metadata.side_effect = VideoScrapingError("extraction failed")

        with pytest.raises(VideoScrapingError, match="extraction failed"):
            await build_page_content(video_service=svc, url="https://youtube.com/watch?v=abc")

        svc.fetch_transcript.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_a_non_video_url_before_touching_the_pipeline(self):
        svc = AsyncMock()
        svc.is_video_url.return_value = False

        with pytest.raises(VideoScrapingError, match="Not a supported video URL"):
            await build_page_content(video_service=svc, url="https://example.com/article")

        svc.fetch_metadata.assert_not_called()
        svc.fetch_transcript.assert_not_called()

    @pytest.mark.asyncio
    async def test_transcript_excerpt_is_truncated(self):
        long_text = "x" * (_TRANSCRIPT_EXCERPT_CHARS + 5000)
        svc = make_video_service(
            metadata=make_extraction(),
            transcript=make_transcript(long_text),
        )

        content = await build_page_content(video_service=svc, url="https://youtube.com/watch?v=abc")

        assert len(content.transcript_excerpt) == _TRANSCRIPT_EXCERPT_CHARS

    @pytest.mark.asyncio
    async def test_no_summaries_yields_empty_summary(self):
        svc = make_video_service(
            metadata=make_extraction(summaries={}), transcript=make_transcript()
        )

        content = await build_page_content(video_service=svc, url="https://youtube.com/watch?v=abc")

        assert content.summary == ""

    @pytest.mark.asyncio
    async def test_first_summary_used_when_no_concise_medium(self):
        svc = make_video_service(
            metadata=make_extraction(
                summaries={"key takeaways:short": "first", "detailed:long": "second"}
            ),
            transcript=make_transcript(),
        )

        content = await build_page_content(video_service=svc, url="https://youtube.com/watch?v=abc")

        assert content.summary == "first"


# --------------------------------------------------------------------------- #
# build_mapper_prompt
# --------------------------------------------------------------------------- #


def test_build_mapper_prompt_contains_key_fields():
    content = VideoPageContent(
        url="https://youtube.com/watch?v=abc",
        title="Prompt Title",
        author="Prompt Author",
        description="Prompt Desc",
        duration=42.0,
        summary="a summary",
        transcript_excerpt="an excerpt",
        platform="youtube",
        language="en",
    )

    prompt = build_mapper_prompt(content)

    assert "Prompt Title" in prompt
    assert "Prompt Author" in prompt
    assert "https://youtube.com/watch?v=abc" in prompt
    assert "a summary" in prompt
    assert "an excerpt" in prompt
    # dropped fields are gone
    assert "Sentiment" not in prompt
    assert "Topics" not in prompt
    assert "schema" in prompt.lower()


# --------------------------------------------------------------------------- #
# get_database_schema
# --------------------------------------------------------------------------- #


class TestGetDatabaseSchema:
    @pytest.mark.asyncio
    async def test_cache_miss_fetches_and_populates_the_cache(self):
        notion = AsyncMock()
        notion.get_database_properties.return_value = {"Name": {"type": "title"}}
        cache = AsyncMock()
        cache.get_artifact.return_value = None

        schema = await get_database_schema(notion_service=notion, cache=cache, database_id="db_1")

        assert schema == {"Name": {"type": "title"}}
        notion.get_database_properties.assert_awaited_once_with("db_1")
        cache.put_artifact.assert_awaited_once_with("db_1", "schema", {"Name": {"type": "title"}})

    @pytest.mark.asyncio
    async def test_cache_hit_never_calls_notion(self):
        notion = AsyncMock()
        cache = AsyncMock()
        cache.get_artifact.return_value = {"Name": {"type": "title"}}

        schema = await get_database_schema(notion_service=notion, cache=cache, database_id="db_1")

        assert schema == {"Name": {"type": "title"}}
        notion.get_database_properties.assert_not_called()
        cache.put_artifact.assert_not_called()


# --------------------------------------------------------------------------- #
# write_video_page
# --------------------------------------------------------------------------- #


def make_payload() -> NotionPagePayload:
    return NotionPagePayload(
        parent={"database_id": "db_123"},
        properties={
            "Name": {"title": [{"text": {"content": "A Video"}}]},
            "URL": {"url": "https://youtube.com/watch?v=abc"},
            "Empty": {},
        },
        children=[
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": "body"}}]},
            }
        ],
    )


def _script_returning(payload: NotionPagePayload):
    def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(payload.model_dump_json())])

    return script


def make_content() -> VideoPageContent:
    return VideoPageContent(
        url="https://youtube.com/watch?v=abc",
        title="A Video",
        author="An Author",
        summary="s",
        transcript_excerpt="e",
    )


class TestWriteVideoPage:
    @pytest.mark.asyncio
    async def test_maps_filters_and_returns_save_result(self):
        settings = make_settings()
        payload = make_payload()
        notion = AsyncMock()
        notion.get_database_properties.return_value = {
            "Name": {"type": "title"},
            "URL": {"type": "url"},
            "Empty": {},
        }
        notion.create_page.return_value = SimpleNamespace(
            id="page_1", url="https://notion.so/page_1"
        )

        agent = build_mapper_agent(settings)
        with agent.override(model=FunctionModel(_script_returning(payload))):
            result = await write_video_page(
                notion_service=notion,
                settings=settings,
                database_id="db_123",
                content=make_content(),
            )

        assert isinstance(result, SaveResult)
        assert result == SaveResult(
            page_id="page_1",
            page_url="https://notion.so/page_1",
            database_id="db_123",
            title="A Video",
        )
        notion.create_page.assert_awaited_once()
        kwargs = notion.create_page.await_args.kwargs
        assert kwargs["database_id"] == "db_123"
        # empty property value filtered out
        assert "Empty" not in kwargs["properties"]
        assert set(kwargs["properties"]) == {"Name", "URL"}
        assert kwargs["children"] == payload.children

    @pytest.mark.asyncio
    async def test_db_schema_passed_in_skips_fetch(self):
        settings = make_settings()
        payload = make_payload()
        notion = AsyncMock()
        notion.create_page.return_value = SimpleNamespace(id="p", url="u")

        agent = build_mapper_agent(settings)
        with agent.override(model=FunctionModel(_script_returning(payload))):
            await write_video_page(
                notion_service=notion,
                settings=settings,
                database_id="db_123",
                content=make_content(),
                db_schema={"Name": {"type": "title"}, "URL": {"type": "url"}, "Empty": {}},
            )

        notion.get_database_properties.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_given_and_no_db_schema_serves_schema_through_cache(self):
        settings = make_settings()
        payload = make_payload()
        notion = AsyncMock()
        notion.get_database_properties.return_value = {
            "Name": {"type": "title"},
            "URL": {"type": "url"},
            "Empty": {},
        }
        notion.create_page.return_value = SimpleNamespace(id="p", url="u")
        cache = AsyncMock()
        cache.get_artifact.return_value = None

        agent = build_mapper_agent(settings)
        with agent.override(model=FunctionModel(_script_returning(payload))):
            await write_video_page(
                notion_service=notion,
                settings=settings,
                database_id="db_123",
                content=make_content(),
                cache=cache,
            )

        # First use: cache missed, so Notion was asked and the result was cached.
        notion.get_database_properties.assert_awaited_once_with("db_123")
        cache.put_artifact.assert_awaited_once()
        assert cache.put_artifact.await_args.args[0] == "db_123"

    @pytest.mark.asyncio
    async def test_cache_hit_skips_the_notion_fetch_entirely(self):
        settings = make_settings()
        payload = make_payload()
        notion = AsyncMock()
        notion.create_page.return_value = SimpleNamespace(id="p", url="u")
        cache = AsyncMock()
        cache.get_artifact.return_value = {
            "Name": {"type": "title"},
            "URL": {"type": "url"},
            "Empty": {},
        }

        agent = build_mapper_agent(settings)
        with agent.override(model=FunctionModel(_script_returning(payload))):
            await write_video_page(
                notion_service=notion,
                settings=settings,
                database_id="db_123",
                content=make_content(),
                cache=cache,
            )

        notion.get_database_properties.assert_not_called()
        cache.put_artifact.assert_not_called()

    @pytest.mark.asyncio
    async def test_mapper_failure_wrapped_in_content_processing_error(self):
        settings = make_settings()
        notion = AsyncMock()

        def boom(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise RuntimeError("model exploded")

        agent = build_mapper_agent(settings)
        with agent.override(model=FunctionModel(boom)):
            with pytest.raises(ContentProcessingError) as exc_info:
                await write_video_page(
                    notion_service=notion,
                    settings=settings,
                    database_id="db_123",
                    content=make_content(),
                    db_schema={"Name": {"type": "title"}},
                )

        assert "Notion mapping failed" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, RuntimeError)
        notion.create_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_page_notion_error_propagates_unwrapped(self):
        settings = make_settings()
        payload = make_payload()
        notion = AsyncMock()
        notion.create_page.side_effect = NotionAuthenticationError("bad token")

        agent = build_mapper_agent(settings)
        with agent.override(model=FunctionModel(_script_returning(payload))):
            with pytest.raises(NotionAuthenticationError, match="bad token"):
                await write_video_page(
                    notion_service=notion,
                    settings=settings,
                    database_id="db_123",
                    content=make_content(),
                    db_schema={"Name": {"type": "title"}, "URL": {"type": "url"}, "Empty": {}},
                )

    @pytest.mark.asyncio
    async def test_usage_forwarded_and_limit_exceeded_propagates(self):
        settings = make_settings()
        payload = make_payload()
        notion = AsyncMock()
        notion.create_page.return_value = SimpleNamespace(id="p", url="u")

        agent = build_mapper_agent(settings)

        # usage forwarded: the shared accumulator records the mapper run
        usage = RunUsage()
        with agent.override(model=FunctionModel(_script_returning(payload))):
            await write_video_page(
                notion_service=notion,
                settings=settings,
                database_id="db_123",
                content=make_content(),
                db_schema={"Name": {"type": "title"}, "URL": {"type": "url"}, "Empty": {}},
                usage=usage,
            )
        assert usage.requests >= 1

        # usage_limits forwarded: a zero request budget raises, unwrapped
        from pydantic_ai.exceptions import UsageLimitExceeded

        with agent.override(model=FunctionModel(_script_returning(payload))):
            with pytest.raises(UsageLimitExceeded):
                await write_video_page(
                    notion_service=notion,
                    settings=settings,
                    database_id="db_123",
                    content=make_content(),
                    db_schema={"Name": {"type": "title"}, "URL": {"type": "url"}, "Empty": {}},
                    usage_limits=UsageLimits(request_limit=0),
                )
