"""The four video tools -- over mocked services, no model, no network."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import models
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior

from webtonotion.agents.deps import AgentDeps
from webtonotion.agents.session.store import Session
from webtonotion.agents.tools.video import (
    ask_about_video,
    get_transcript,
    get_video_metadata,
    summarize,
)
from webtonotion.config.settings import Settings
from webtonotion.exceptions import ContentProcessingError, VideoScrapingError
from webtonotion.models.chat import AnswerAttempt, ToolError
from webtonotion.models.transcript import StoredTranscript, TranscriptSegment
from webtonotion.services.extraction.base import ExtractionData

models.ALLOW_MODEL_REQUESTS = False

URL = "https://www.example.com/watch?v=abc123"


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


def make_transcript() -> StoredTranscript:
    return StoredTranscript(
        text="a long spoken passage",
        language="en",
        duration=30.0,
        segments=[TranscriptSegment(start=0.0, end=30.0, text="a long spoken passage")],
    )


def make_ctx() -> MagicMock:
    video_service = MagicMock()
    video_service.fetch_metadata = AsyncMock(
        return_value=ExtractionData(
            url=URL,
            title="Test Video",
            description="d",
            author="Test Author",
            duration=30.0,
            published_at=None,
            metadata={"platform": "youtube", "video_id": "abc123"},
        )
    )
    video_service.fetch_transcript = AsyncMock(return_value=make_transcript())
    video_service.store_summary = AsyncMock(return_value=None)

    cache = MagicMock()
    cache.get_artifact = AsyncMock(return_value=None)
    cache.put_artifact = AsyncMock(return_value=None)

    ctx = MagicMock()
    ctx.deps = AgentDeps(
        notion_service=MagicMock(),
        session=make_session(),
        store=MagicMock(),
        settings=make_settings(),
        video_service=video_service,
        cache=cache,
    )
    return ctx


class TestGetVideoMetadata:
    @pytest.mark.asyncio
    async def test_returns_chat_sized_metadata(self):
        ctx = make_ctx()

        result = await get_video_metadata(ctx, URL)

        assert result.title == "Test Video"
        assert result.author == "Test Author"
        assert result.platform == "youtube"
        assert result.duration == 30.0

    @pytest.mark.asyncio
    async def test_service_failure_becomes_a_tool_error_not_an_exception(self):
        ctx = make_ctx()
        ctx.deps.video_service.fetch_metadata = AsyncMock(
            side_effect=VideoScrapingError("geo-blocked")
        )

        result = await get_video_metadata(ctx, URL)

        assert isinstance(result, ToolError)
        assert "geo-blocked" in (result.detail or "")

    @pytest.mark.asyncio
    async def test_never_leaks_the_transcript_now_that_it_lives_in_metadata(self):
        """The transcript is stored in the metadata artifact, so fetch_metadata can
        return an ExtractionData carrying it. The tool must still hand the agent only
        the chat-sized fields -- never the transcript body."""
        ctx = make_ctx()
        ctx.deps.video_service.fetch_metadata = AsyncMock(
            return_value=ExtractionData(
                url=URL,
                title="Test Video",
                description="d",
                author="Test Author",
                duration=30.0,
                metadata={"platform": "youtube"},
                transcript=make_transcript(),
            )
        )

        result = await get_video_metadata(ctx, URL)

        assert not hasattr(result, "transcript")
        assert "spoken passage" not in result.model_dump_json()


class TestGetTranscript:
    @pytest.mark.asyncio
    async def test_returns_a_ref_not_the_body(self):
        ctx = make_ctx()

        result = await get_transcript(ctx, URL)

        assert result.char_count == len("a long spoken passage")
        assert result.preview.startswith("a long spoken")
        assert not hasattr(result, "text")

    @pytest.mark.asyncio
    async def test_missing_audio_becomes_a_tool_error(self):
        ctx = make_ctx()
        ctx.deps.video_service.fetch_transcript = AsyncMock(
            side_effect=VideoScrapingError("no audio track")
        )

        result = await get_transcript(ctx, URL)

        assert isinstance(result, ToolError)


class TestSummarize:
    @pytest.mark.asyncio
    async def test_serves_a_cached_summary_without_running_a_sub_agent(self):
        ctx = make_ctx()
        ctx.deps.cache.get_artifact = AsyncMock(
            return_value={"summaries": {"concise:medium": "cached summary"}}
        )

        with patch("webtonotion.agents.tools.video.summarize_text") as run_summary:
            result = await summarize(ctx, URL, style="concise", length="medium")

        assert result.summary == "cached summary"
        run_summary.assert_not_called()
        ctx.deps.cache.get_artifact.assert_awaited_once_with(URL, "metadata")

    @pytest.mark.asyncio
    async def test_runs_the_sub_agent_and_delegates_persistence_to_the_service(self):
        """The tool runs the sub-agent, then hands the summary to
        ``video_service.store_summary``, which takes the metadata artifact lock and
        merges -- the tool never touches the cache file itself."""
        ctx = make_ctx()
        ctx.deps.cache.get_artifact = AsyncMock(return_value=None)

        with (
            patch("webtonotion.agents.tools.video.build_summary_agent"),
            patch(
                "webtonotion.agents.tools.video.summarize_text",
                new=AsyncMock(return_value="fresh summary"),
            ),
        ):
            result = await summarize(ctx, URL, style="bullet points", length="short")

        assert result.summary == "fresh summary"
        assert result.style == "bullet points"
        ctx.deps.cache.put_artifact.assert_not_awaited()
        ctx.deps.video_service.store_summary.assert_awaited_once_with(
            URL, "bullet points:short", "fresh summary"
        )

    @pytest.mark.asyncio
    async def test_shares_the_orchestrator_run_s_usage_and_limits_with_the_sub_agent(self):
        """summarize must pass the orchestrator's ctx.usage/ctx.usage_limits through to
        the sub-agent run, so sub-agent requests count against the same turn budget
        (the agent-delegation pattern of sharing usage across delegates)."""
        ctx = make_ctx()
        ctx.deps.cache.get_artifact = AsyncMock(return_value=None)

        with (
            patch("webtonotion.agents.tools.video.build_summary_agent"),
            patch(
                "webtonotion.agents.tools.video.summarize_text",
                new=AsyncMock(return_value="fresh summary"),
            ) as run_summary,
        ):
            await summarize(ctx, URL, style="concise", length="medium")

        assert run_summary.call_args.kwargs["usage"] is ctx.usage
        assert run_summary.call_args.kwargs["usage_limits"] is ctx.usage_limits

    @pytest.mark.asyncio
    async def test_a_sub_agent_failure_becomes_a_tool_error_and_stores_nothing(self):
        ctx = make_ctx()
        ctx.deps.cache.get_artifact = AsyncMock(return_value=None)

        with (
            patch("webtonotion.agents.tools.video.build_summary_agent"),
            patch(
                "webtonotion.agents.tools.video.summarize_text",
                new=AsyncMock(side_effect=ContentProcessingError("model down")),
            ),
        ):
            result = await summarize(ctx, URL, style="bullet points", length="short")

        assert isinstance(result, ToolError)
        ctx.deps.video_service.store_summary.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_transient_provider_error_becomes_a_tool_error_not_a_500(self):
        ctx = make_ctx()
        ctx.deps.cache.get_artifact = AsyncMock(return_value=None)

        with (
            patch("webtonotion.agents.tools.video.build_summary_agent"),
            patch(
                "webtonotion.agents.tools.video.summarize_text",
                new=AsyncMock(
                    side_effect=ModelHTTPError(status_code=503, model_name="m", body=None)
                ),
            ),
        ):
            result = await summarize(ctx, URL, style="concise", length="medium")

        assert isinstance(result, ToolError)
        ctx.deps.video_service.store_summary.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_bad_api_key_still_raises(self):
        """A 401 is a configuration error: no agent reasoning recovers from it, so it
        must keep propagating rather than being hidden in a ToolError."""
        ctx = make_ctx()
        ctx.deps.cache.get_artifact = AsyncMock(return_value=None)

        with (
            patch("webtonotion.agents.tools.video.build_summary_agent"),
            patch(
                "webtonotion.agents.tools.video.summarize_text",
                new=AsyncMock(
                    side_effect=ModelHTTPError(status_code=401, model_name="m", body=None)
                ),
            ),
            pytest.raises(ModelHTTPError),
        ):
            await summarize(ctx, URL, style="concise", length="medium")


class TestAskAboutVideo:
    @pytest.mark.asyncio
    async def test_passes_a_cached_summary_as_the_compact_context(self):
        ctx = make_ctx()
        ctx.deps.cache.get_artifact = AsyncMock(
            return_value={"summaries": {"concise:medium": "cached summary"}}
        )
        answer = AnswerAttempt(answer="42", sufficient=True, excerpts=["[00:00] passage"])

        with (
            patch("webtonotion.agents.tools.video.build_answer_agent"),
            patch(
                "webtonotion.agents.tools.video.answer_question",
                new=AsyncMock(return_value=answer),
            ) as run_answer,
        ):
            result = await ask_about_video(ctx, URL, "what is the answer?")

        assert result.answer == "42"
        assert result.excerpts == ["[00:00] passage"]
        assert run_answer.call_args.args[3] == "cached summary"
        assert run_answer.call_args.kwargs["usage"] is ctx.usage
        assert run_answer.call_args.kwargs["usage_limits"] is ctx.usage_limits
        ctx.deps.cache.get_artifact.assert_awaited_once_with(URL, "metadata")

    @pytest.mark.asyncio
    async def test_uses_any_available_summary_as_fallback_compact_context(self):
        ctx = make_ctx()
        ctx.deps.cache.get_artifact = AsyncMock(
            return_value={"summaries": {"detailed:long": "fallback summary"}}
        )
        answer = AnswerAttempt(answer="42", sufficient=True, excerpts=["[00:00] passage"])

        with (
            patch("webtonotion.agents.tools.video.build_answer_agent"),
            patch(
                "webtonotion.agents.tools.video.answer_question",
                new=AsyncMock(return_value=answer),
            ) as run_answer,
        ):
            result = await ask_about_video(ctx, URL, "what is the answer?")

        assert result.answer == "42"
        assert run_answer.call_args.args[3] == "fallback summary"

    @pytest.mark.asyncio
    async def test_transcript_failure_becomes_a_tool_error(self):
        ctx = make_ctx()
        ctx.deps.video_service.fetch_transcript = AsyncMock(
            side_effect=VideoScrapingError("no audio track")
        )

        result = await ask_about_video(ctx, URL, "what is the answer?")

        assert isinstance(result, ToolError)

    @pytest.mark.asyncio
    async def test_a_malformed_model_response_becomes_a_tool_error(self):
        ctx = make_ctx()
        ctx.deps.cache.get_artifact = AsyncMock(return_value=None)

        with (
            patch("webtonotion.agents.tools.video.build_answer_agent"),
            patch(
                "webtonotion.agents.tools.video.answer_question",
                new=AsyncMock(side_effect=UnexpectedModelBehavior("garbled output")),
            ),
        ):
            result = await ask_about_video(ctx, URL, "what is the answer?")

        assert isinstance(result, ToolError)
