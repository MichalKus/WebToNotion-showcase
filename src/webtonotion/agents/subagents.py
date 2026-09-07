"""Ephemeral sub-agents that read a transcript.

The orchestrator never sees a transcript. It holds a :class:`TranscriptRef` and calls a
tool; the tool starts a sub-agent run here, the transcript enters that run, and the run
ends when the tool returns a summary or an answer. Nothing about the body is persisted
in conversation history.

Two cost mechanisms live here, in order of impact:

1. **Prompt caching** — every prompt goes through ``build_transcript_prompt``, so
   repeated questions about one video reuse a cached prefix.
2. **Escalation** — ``answer_question`` first tries a compact context (a cached summary
   plus a timestamped segment index, roughly 1-2k tokens) and loads the full transcript
   only when the sub-agent reports that context was insufficient. Most follow-ups never
   need the raw text.
3. **Map-reduce above a ceiling** — past ``summary_map_reduce_threshold_chars``,
   summarization runs over windows and reduces, bounding *context size* regardless of
   the model's context limit so one pathological six-hour stream cannot exceed it. The
   *cost* is bounded separately: ``usage``/``usage_limits`` passed in from the caller's
   ``RunContext`` make every sub-agent request count against the same turn-wide budget
   (see ``agents/tools/video.py`` and ``Settings.agent_max_total_tokens``), following the
   agent-delegation pattern of sharing ``ctx.usage`` across delegate runs.

Agents are built by factory functions, never at module import: constructing an
OpenRouter model at import time requires an API key. The factories are cached by the
settings values that determine the underlying client (model name, API key, retries) so
a tool call reuses one agent/HTTP client instead of building a fresh one every time;
``Settings`` itself isn't hashable, so the cache key is the individual scalar fields.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.usage import RunUsage, UsageLimits

from webtonotion.agents.prompts import (
    ANSWER_INSTRUCTIONS,
    SUMMARY_INSTRUCTIONS,
    build_segment_index,
    build_transcript_prompt,
)
from webtonotion.models.chat import AnswerAttempt, SummaryLength, SummaryStyle
from webtonotion.models.transcript import StoredTranscript

if TYPE_CHECKING:
    from webtonotion.config.settings import Settings


def _build_model(model_name: str, api_key: str) -> OpenRouterModel:
    """Construct the OpenRouter model for a sub-agent run."""
    return OpenRouterModel(
        model_name,
        provider=OpenRouterProvider(api_key=api_key),
    )


@lru_cache(maxsize=4)
def _summary_agent(model_name: str, api_key: str, retries: int) -> Agent[None, str]:
    return Agent(
        _build_model(model_name, api_key),
        output_type=str,
        retries=retries,
        instructions=SUMMARY_INSTRUCTIONS,
        name="summary_subagent",
    )


@lru_cache(maxsize=4)
def _answer_agent(model_name: str, api_key: str, retries: int) -> Agent[None, AnswerAttempt]:
    return Agent(
        _build_model(model_name, api_key),
        output_type=AnswerAttempt,
        retries=retries,
        instructions=ANSWER_INSTRUCTIONS,
        name="answer_subagent",
    )


def build_summary_agent(settings: "Settings") -> Agent[None, str]:
    """Return the (cached) summarization sub-agent for ``settings``."""
    return _summary_agent(
        settings.openrouter_model, settings.openrouter_api_key or "unset", settings.max_retries
    )


def build_answer_agent(settings: "Settings") -> Agent[None, AnswerAttempt]:
    """Return the (cached) question-answering sub-agent for ``settings``.

    Its structured ``AnswerAttempt`` output is what makes escalation possible: the model
    tells the caller whether the context it was given was enough.
    """
    return _answer_agent(
        settings.openrouter_model, settings.openrouter_api_key or "unset", settings.max_retries
    )


def _summary_request(style: SummaryStyle | str, length: SummaryLength | str) -> str:
    """The varying tail of a summarization prompt."""
    return (
        f"Summarize the video material above. Style: {style}. Length: {length}. "
        "Return only the summary."
    )


async def summarize_text(
    agent: Agent[None, str],
    text: str,
    style: SummaryStyle | str,
    length: SummaryLength | str,
    settings: "Settings",
    *,
    usage: RunUsage | None = None,
    usage_limits: UsageLimits | None = None,
) -> str:
    """Summarize ``text``, mapping over windows when it exceeds the ceiling.

    ``usage``/``usage_limits`` are the caller's ``RunContext`` fields, passed straight
    through so every request here counts against the same turn-wide budget as the
    orchestrator (the agent-delegation pattern: sharing ``ctx.usage`` across delegates).
    """
    threshold = settings.summary_map_reduce_threshold_chars
    if len(text) <= threshold:
        result = await agent.run(
            build_transcript_prompt(text, _summary_request(style, length)),
            usage=usage,
            usage_limits=usage_limits,
        )
        return result.output

    window = settings.summary_map_reduce_window_chars
    partials: list[str] = []
    for start in range(0, len(text), window):
        chunk_result = await agent.run(
            build_transcript_prompt(
                text[start : start + window], _summary_request("concise", "short")
            ),
            usage=usage,
            usage_limits=usage_limits,
        )
        partials.append(chunk_result.output)

    reduced = await agent.run(
        build_transcript_prompt("\n\n".join(partials), _summary_request(style, length)),
        usage=usage,
        usage_limits=usage_limits,
    )
    return reduced.output


async def answer_question(
    agent: Agent[None, AnswerAttempt],
    transcript: StoredTranscript,
    question: str,
    compact_context: str | None,
    *,
    usage: RunUsage | None = None,
    usage_limits: UsageLimits | None = None,
) -> AnswerAttempt:
    """Answer ``question`` about ``transcript``, escalating only when necessary.

    When ``compact_context`` is provided (typically a cached summary), a first pass runs
    against it plus a timestamped segment index. If the sub-agent reports the context
    was insufficient, a second pass runs against the full transcript. With no compact
    context available, the full transcript is used immediately.

    ``usage``/``usage_limits`` are the caller's ``RunContext`` fields, passed straight
    through so both passes count against the same turn-wide budget as the orchestrator.
    """
    if compact_context:
        index = build_segment_index(transcript.segments)
        first_body = compact_context if not index else f"{compact_context}\n\n{index}"
        first = await agent.run(
            build_transcript_prompt(first_body, question),
            usage=usage,
            usage_limits=usage_limits,
        )
        if first.output.sufficient:
            return first.output

    escalated = await agent.run(
        build_transcript_prompt(transcript.text, question),
        usage=usage,
        usage_limits=usage_limits,
    )
    return escalated.output
