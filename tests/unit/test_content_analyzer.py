"""ContentAnalyzer.analyze surfaces failures as a typed error.

Supersedes the pre-refactor characterization test, which pinned the old silent
fallback (`content_analyzer.py:113`). That fallback returned an empty
ContentAnalysisResult -- except `topics` has `min_items=1`, so constructing it raised
an unrelated pydantic ValidationError and the real OpenRouter error was lost. The
agentic orchestrator spec replaces it with a typed failure the agent can see and
report, rather than plausible-looking empty analysis it would believe.

HTTP behaviour is unchanged: `process_video` wraps either error in
VideoScrapingError, which `api/process.py` maps to 422.
"""

from unittest.mock import patch

import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel

from webtonotion.config.settings import settings
from webtonotion.exceptions import ContentProcessingError
from webtonotion.services.analysis.content_analyzer import ContentAnalyzer

models.ALLOW_MODEL_REQUESTS = False


def make_analyzer() -> ContentAnalyzer:
    """Construct a ContentAnalyzer without needing a real OpenRouter key.

    ContentAnalyzer.__init__ eagerly requires settings.openrouter_api_key to be
    truthy, which is unset in CI. The real model is never used -- the agent's model
    is overridden below -- so a placeholder key is sufficient.
    """
    with patch.object(settings, "openrouter_api_key", "test-key"):
        return ContentAnalyzer()


async def _raise_model_error(messages: list[ModelMessage], info: AgentInfo) -> None:
    raise RuntimeError("OpenRouter model unavailable")


class TestContentAnalyzerFailureMode:
    @pytest.mark.asyncio
    async def test_run_failure_raises_content_processing_error(self):
        analyzer = make_analyzer()

        with analyzer.analysis_agent.override(model=FunctionModel(_raise_model_error)):
            with pytest.raises(ContentProcessingError):
                await analyzer.analyze({"title": "t", "description": "d"}, "transcript")

    @pytest.mark.asyncio
    async def test_original_error_is_chained_as_the_cause(self):
        analyzer = make_analyzer()

        with analyzer.analysis_agent.override(model=FunctionModel(_raise_model_error)):
            with pytest.raises(ContentProcessingError) as exc_info:
                await analyzer.analyze({"title": "t", "description": "d"}, "transcript")

        assert isinstance(exc_info.value.__cause__, RuntimeError)
        assert "OpenRouter model unavailable" in str(exc_info.value.__cause__)
