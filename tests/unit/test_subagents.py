"""Sub-agent behaviour: escalation on insufficient context, map-reduce above the ceiling."""

import pytest
from pydantic_ai import ModelResponse, TextPart, ToolCallPart, models
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage

from webtonotion.agents.subagents import (
    answer_question,
    build_answer_agent,
    build_summary_agent,
    summarize_text,
)
from webtonotion.config.settings import Settings
from webtonotion.models.transcript import StoredTranscript, TranscriptSegment

models.ALLOW_MODEL_REQUESTS = False


def make_settings(**overrides) -> Settings:
    """Build Settings with field overrides.

    `Settings` has `extra="ignore"`, so a typo in an override name is silently
    dropped rather than raising -- keep these names in sync with settings.py.
    """
    return Settings(openrouter_api_key="test-key", **overrides)


def make_transcript(text: str = "some words") -> StoredTranscript:
    return StoredTranscript(
        text=text,
        language="en",
        duration=20.0,
        segments=[
            TranscriptSegment(start=0.0, end=10.0, text="first half"),
            TranscriptSegment(start=10.0, end=20.0, text="second half"),
        ],
    )


class TestSummarize:
    @pytest.mark.asyncio
    async def test_short_text_runs_the_model_once(self):
        settings = make_settings()
        agent = build_summary_agent(settings)
        calls: list[int] = []

        def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            calls.append(1)
            return ModelResponse(parts=[TextPart("a summary")])

        with agent.override(model=FunctionModel(script)):
            result = await summarize_text(agent, "short text", "concise", "short", settings)

        assert result == "a summary"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_long_text_maps_over_windows_then_reduces(self):
        settings = make_settings(
            summary_map_reduce_threshold_chars=2000,
            summary_map_reduce_window_chars=1000,
        )
        agent = build_summary_agent(settings)
        calls: list[int] = []

        def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            calls.append(1)
            return ModelResponse(parts=[TextPart(f"part {len(calls)}")])

        with agent.override(model=FunctionModel(script)):
            result = await summarize_text(agent, "x" * 2400, "concise", "short", settings)

        # 3 windows of 1000 chars + 1 reduce call
        assert len(calls) == 4
        assert result == "part 4"

    @pytest.mark.asyncio
    async def test_shared_usage_accumulates_across_every_map_reduce_window(self):
        """A caller-supplied RunUsage (the orchestrator's ctx.usage) must see every
        request the sub-agent makes, not just the orchestrator's own -- this is what
        makes the turn-wide usage budget and the API's usage summary correct."""
        settings = make_settings(
            summary_map_reduce_threshold_chars=2000,
            summary_map_reduce_window_chars=1000,
        )
        agent = build_summary_agent(settings)

        def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("part")])

        usage = RunUsage()
        with agent.override(model=FunctionModel(script)):
            await summarize_text(agent, "x" * 2400, "concise", "short", settings, usage=usage)

        # 3 map windows + 1 reduce call, all counted on the shared usage object.
        assert usage.requests == 4

    @pytest.mark.asyncio
    async def test_build_summary_agent_reuses_the_same_instance_for_equal_settings(self):
        settings_a = make_settings()
        settings_b = make_settings()

        assert build_summary_agent(settings_a) is build_summary_agent(settings_b)

    @pytest.mark.asyncio
    async def test_build_summary_agent_builds_a_new_instance_for_a_different_model(self):
        settings_a = make_settings()
        settings_b = make_settings(openrouter_model="anthropic/claude-3.5-sonnet")

        assert build_summary_agent(settings_a) is not build_summary_agent(settings_b)


class TestAnswerEscalation:
    @pytest.mark.asyncio
    async def test_sufficient_first_pass_never_loads_the_full_body(self):
        settings = make_settings()
        agent = build_answer_agent(settings)
        seen_prefixes: list[str] = []

        def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen_prefixes.append(str(messages[-1].parts[0].content[0]))
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "final_result",
                        {"answer": "yes", "sufficient": True, "excerpts": []},
                    )
                ]
            )

        transcript = make_transcript("THE FULL BODY TEXT")
        with agent.override(model=FunctionModel(script)):
            result = await answer_question(agent, transcript, "is it?", "a cached summary")

        assert result.answer == "yes"
        assert len(seen_prefixes) == 1
        assert "THE FULL BODY TEXT" not in seen_prefixes[0]

    @pytest.mark.asyncio
    async def test_insufficient_first_pass_escalates_to_the_full_body(self):
        settings = make_settings()
        agent = build_answer_agent(settings)
        seen_prefixes: list[str] = []

        def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen_prefixes.append(str(messages[-1].parts[0].content[0]))
            sufficient = len(seen_prefixes) > 1
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "final_result",
                        {
                            "answer": f"pass {len(seen_prefixes)}",
                            "sufficient": sufficient,
                            "excerpts": [],
                        },
                    )
                ]
            )

        transcript = make_transcript("THE FULL BODY TEXT")
        with agent.override(model=FunctionModel(script)):
            result = await answer_question(agent, transcript, "is it?", "a cached summary")

        assert result.answer == "pass 2"
        assert len(seen_prefixes) == 2
        assert "THE FULL BODY TEXT" in seen_prefixes[1]

    @pytest.mark.asyncio
    async def test_shared_usage_accumulates_across_both_escalation_passes(self):
        settings = make_settings()
        agent = build_answer_agent(settings)
        seen = 0

        def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            nonlocal seen
            seen += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "final_result",
                        {"answer": f"pass {seen}", "sufficient": seen > 1, "excerpts": []},
                    )
                ]
            )

        transcript = make_transcript("THE FULL BODY TEXT")
        usage = RunUsage()
        with agent.override(model=FunctionModel(script)):
            await answer_question(agent, transcript, "is it?", "a cached summary", usage=usage)

        assert usage.requests == 2

    @pytest.mark.asyncio
    async def test_no_compact_context_goes_straight_to_the_full_body(self):
        settings = make_settings()
        agent = build_answer_agent(settings)
        seen_prefixes: list[str] = []

        def script(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen_prefixes.append(str(messages[-1].parts[0].content[0]))
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "final_result",
                        {"answer": "direct", "sufficient": True, "excerpts": []},
                    )
                ]
            )

        transcript = make_transcript("THE FULL BODY TEXT")
        with agent.override(model=FunctionModel(script)):
            result = await answer_question(agent, transcript, "is it?", None)

        assert result.answer == "direct"
        assert len(seen_prefixes) == 1
        assert "THE FULL BODY TEXT" in seen_prefixes[0]
