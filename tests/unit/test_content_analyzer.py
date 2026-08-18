"""Characterization test for ContentAnalyzer.analyze's failure mode.

Pins current behaviour (content_analyzer.py:113): when the underlying agent
run raises, `analyze` is *intended* to swallow the error and return an
empty ContentAnalysisResult. It does not: `ContentAnalysisResult.topics`
has `min_items=1` (models/video.py), so the fallback construction
`ContentAnalysisResult(topics=[], ...)` itself raises a pydantic
`ValidationError`. The original OpenRouter error is logged but never
surfaces -- callers instead see an unrelated validation error. This test
pins that actual (broken) behaviour. The agentic orchestrator spec's
error-handling section replaces this whole fallback with a typed failure.
"""

from unittest.mock import patch

import pytest
from pydantic import ValidationError
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel

from webtonotion.config.settings import settings
from webtonotion.services.analysis.content_analyzer import ContentAnalyzer

models.ALLOW_MODEL_REQUESTS = False


def make_analyzer() -> ContentAnalyzer:
    """Construct a ContentAnalyzer without needing a real OpenRouter key.

    ContentAnalyzer.__init__ eagerly requires settings.openrouter_api_key to
    be truthy, which is unset in CI. The real model is never used in these
    tests -- the agent's model is overridden below -- so a placeholder key
    is sufficient.
    """
    with patch.object(settings, "openrouter_api_key", "test-key"):
        return ContentAnalyzer()


async def _raise_model_error(messages: list[ModelMessage], info: AgentInfo) -> None:
    raise RuntimeError("OpenRouter model unavailable")


class TestContentAnalyzerFailureMode:
    @pytest.mark.asyncio
    async def test_analyze_raises_validation_error_when_agent_run_fails(self):
        analyzer = make_analyzer()

        with analyzer.analysis_agent.override(model=FunctionModel(_raise_model_error)):
            with pytest.raises(ValidationError):
                await analyzer.analyze(
                    {"title": "Test Video", "description": "desc", "extractor": "youtube"},
                    "transcript text",
                )
