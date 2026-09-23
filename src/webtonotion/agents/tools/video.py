"""Video tools: the orchestrator's read path over a video.

Every tool returns a small Pydantic model sized for chat context, and every one turns a
recoverable service failure into a structured :class:`ToolError` rather than an
exception. A geo-blocked video or a missing audio track is something the agent should
see, explain, and offer alternatives for -- aborting the run and surfacing a 500 for it
would be wrong. The same goes for a transient model-provider failure mid-summarization
(a 5xx, a 429, a timeout): the agent can relay it and the user can retry. Configuration
failures (a missing API key, a 401/403) still raise, because no amount of agent
reasoning recovers from them -- and a :class:`UsageLimitExceeded` still propagates, so
the turn-budget guard keeps mapping to HTTP 429.

``get_transcript`` returning a *reference* is what keeps a 50k-character transcript out
of conversation history. The body only ever enters the ephemeral sub-agent runs in
``agents/subagents.py``.
"""

from __future__ import annotations

from typing import Union

from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior

from webtonotion.agents.deps import AgentDeps
from webtonotion.agents.errors import FATAL_AUTH_HTTP_STATUS, RECOVERABLE_VIDEO_ERRORS
from webtonotion.agents.subagents import (
    answer_question,
    build_answer_agent,
    build_summary_agent,
    summarize_text,
)
from webtonotion.config.logging import get_logger
from webtonotion.models.chat import (
    AnswerResult,
    SummaryLength,
    SummaryResult,
    SummaryStyle,
    ToolError,
    VideoMetadata,
)
from webtonotion.models.transcript import TranscriptRef

logger = get_logger(__name__)

# Model-provider failures from a sub-agent run. Transient ones (5xx, 429, timeouts,
# malformed responses) become a ToolError; a 401/403 is a config error and re-raises.
_MODEL_PROVIDER_ERROR = (ModelAPIError, UnexpectedModelBehavior)


def _sub_agent_tool_error(exc: Exception, reason: str) -> ToolError:
    """Convert a transient sub-agent model failure to a ToolError, or re-raise.

    A bad API key (401/403) is not something the orchestrator can work around, so it
    keeps propagating; everything else -- a provider 5xx, a rate-limit 429 from the
    provider, a dropped connection, an unparseable response -- is reported to the agent
    so the turn is not lost to a 500.
    """
    if isinstance(exc, ModelHTTPError) and exc.status_code in FATAL_AUTH_HTTP_STATUS:
        raise exc
    return ToolError(reason=reason, detail=str(exc))


def _summary_key(style: SummaryStyle | str, length: SummaryLength | str) -> str:
    """Dictionary key for one summary variant within metadata['summaries']."""
    return f"{style}:{length}"


async def get_video_metadata(
    ctx: RunContext[AgentDeps], url: str
) -> Union[VideoMetadata, ToolError]:
    """Return a video's title, author, duration, and platform.

    Metadata-only: this never downloads audio, so answering "what is this video?" costs
    one yt-dlp metadata call.
    """
    try:
        data = await ctx.deps.video_service.fetch_metadata(url)
    except RECOVERABLE_VIDEO_ERRORS as e:
        logger.warning(f"get_video_metadata failed for {url}: {e}")
        return ToolError(reason="Could not read this video's metadata.", detail=str(e))

    return VideoMetadata(
        url=url,
        title=data.title,
        author=data.author,
        duration=data.duration,
        platform=str(data.metadata.get("platform", "unknown")),
        published_at=data.published_at,
    )


async def get_transcript(ctx: RunContext[AgentDeps], url: str) -> Union[TranscriptRef, ToolError]:
    """Transcribe a video and return a handle to the transcript.

    The return value is a reference -- hash, character count, duration, language, and a
    short preview -- not the transcript itself. Pass the same URL to ``summarize`` or
    ``ask_about_video`` to work with the body.
    """
    try:
        transcript = await ctx.deps.video_service.fetch_transcript(url)
    except RECOVERABLE_VIDEO_ERRORS as e:
        logger.warning(f"get_transcript failed for {url}: {e}")
        return ToolError(reason="Could not transcribe this video.", detail=str(e))

    return TranscriptRef.from_transcript(
        url, transcript, ctx.deps.settings.transcript_preview_chars
    )


async def summarize(
    ctx: RunContext[AgentDeps],
    url: str,
    style: SummaryStyle = "concise",
    length: SummaryLength = "medium",
) -> Union[SummaryResult, ToolError]:
    """Summarize a video, in the style and length the user asked for.

    Args:
        url: The video to summarize.
        style: How to write it: "concise", "bullet points", "detailed", "for a beginner", or "key takeaways".
        length: Desired length: "short", "medium", or "long".
    """
    key = _summary_key(style, length)
    meta = await ctx.deps.cache.get_artifact(url, "metadata")
    if meta and isinstance(meta.get("summaries"), dict) and meta["summaries"].get(key):
        return SummaryResult(url=url, style=style, length=length, summary=meta["summaries"][key])

    try:
        transcript = await ctx.deps.video_service.fetch_transcript(url)
    except RECOVERABLE_VIDEO_ERRORS as e:
        logger.warning(f"summarize failed to obtain a transcript for {url}: {e}")
        return ToolError(reason="Could not read this video to summarize it.", detail=str(e))

    agent = build_summary_agent(ctx.deps.settings)
    try:
        summary = await summarize_text(
            agent,
            transcript.text,
            style,
            length,
            ctx.deps.settings,
            usage=ctx.usage,
            usage_limits=ctx.usage_limits,
        )
    except RECOVERABLE_VIDEO_ERRORS as e:
        logger.warning(f"summarize failed for {url}: {e}")
        return ToolError(reason="Could not summarize this video.", detail=str(e))
    except _MODEL_PROVIDER_ERROR as e:
        logger.warning(f"summarize hit a model-provider error for {url}: {e}")
        return _sub_agent_tool_error(e, "The summarizer model is temporarily unavailable.")

    # The service takes the metadata artifact lock and merges, so a concurrent
    # summarize for a different style:length on this URL is not clobbered.
    await ctx.deps.video_service.store_summary(url, key, summary)
    return SummaryResult(url=url, style=style, length=length, summary=summary)


async def ask_about_video(
    ctx: RunContext[AgentDeps], url: str, question: str
) -> Union[AnswerResult, ToolError]:
    """Answer a question about a video, citing the excerpts the answer rests on.

    Answers from a cached summary and a timestamped segment index first, loading the
    full transcript only when that is not enough.
    """
    try:
        transcript = await ctx.deps.video_service.fetch_transcript(url)
    except RECOVERABLE_VIDEO_ERRORS as e:
        logger.warning(f"ask_about_video failed to obtain a transcript for {url}: {e}")
        return ToolError(reason="Could not read this video to answer about it.", detail=str(e))

    meta = await ctx.deps.cache.get_artifact(url, "metadata")
    summaries = (meta or {}).get("summaries", {})
    compact_context = None
    if isinstance(summaries, dict):
        compact_context = summaries.get("concise:medium") or next(iter(summaries.values()), None)

    agent = build_answer_agent(ctx.deps.settings)
    try:
        attempt = await answer_question(
            agent,
            transcript,
            question,
            compact_context,
            usage=ctx.usage,
            usage_limits=ctx.usage_limits,
        )
    except RECOVERABLE_VIDEO_ERRORS as e:
        logger.warning(f"ask_about_video failed for {url}: {e}")
        return ToolError(reason="Could not answer that about this video.", detail=str(e))
    except _MODEL_PROVIDER_ERROR as e:
        logger.warning(f"ask_about_video hit a model-provider error for {url}: {e}")
        return _sub_agent_tool_error(e, "The model is temporarily unavailable.")

    return AnswerResult(
        url=url,
        question=question,
        answer=attempt.answer,
        excerpts=attempt.excerpts,
    )
