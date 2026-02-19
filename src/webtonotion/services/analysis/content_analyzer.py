"""Content analysis service using PydanticAI with OpenRouter."""

from typing import Any, Dict

from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from webtonotion.config.logging import LoggerMixin
from webtonotion.config.settings import settings
from webtonotion.models.video import ContentAnalysisResult


class ContentAnalyzer(LoggerMixin):
    """Service for analyzing video content using AI with OpenRouter."""

    def __init__(self) -> None:
        """Initialize the content analysis service with OpenRouter."""
        if not settings.openrouter_api_key:
            raise ValueError("OpenRouter API key is required for content analysis")

        self.logger.debug(
            f"Initializing ContentAnalyzer with OpenRouter using model: {settings.openrouter_model}"
        )

        # Create OpenRouter model with provider
        model = OpenRouterModel(
            settings.openrouter_model,
            provider=OpenRouterProvider(api_key=settings.openrouter_api_key),
        )

        self.analysis_agent = Agent(
            model=model, output_type=ContentAnalysisResult, system_prompt=self._get_system_prompt()
        )

    def _get_system_prompt(self) -> str:
        """Get the system prompt for content analysis."""
        return """You are an expert content analyst specializing in video content analysis.
        
        Your task is to analyze video content and extract structured information including:
        1. Main topics and themes (maximum 10 most relevant topics)
        2. Overall sentiment (positive, negative, or neutral)
        3. Geographic locations mentioned in the content
        4. Key insights and takeaways (maximum 5 most important)
        5. Primary content category
        
        Base your analysis on the provided title, description, and transcript.
        Be precise and focus on the most relevant and significant elements.
        For sentiment, consider the overall tone and message of the content.
        For topics, extract concrete themes, subjects, or concepts discussed.
        For locations, identify specific places, cities, countries, or regions mentioned.
        For insights, summarize the most valuable takeaways or conclusions.
        For category, classify the content type (educational, entertainment, news, tutorial, etc.).
        """

    async def analyze(self, info: Dict[str, Any], transcript: str) -> ContentAnalysisResult:
        """Analyze video content using AI with structured output."""
        try:
            # Prepare structured content for analysis
            content_data = {
                "title": info.get("title", ""),
                "description": info.get("description", ""),
                "platform": info.get("extractor", "unknown"),
                "transcript": transcript,
            }

            # Create comprehensive analysis prompt
            analysis_prompt = f"""
                Analyze the following video content:
            
                Title: {content_data['title']}
                Platform: {content_data.get('platform', 'unknown')}
            
                Description:
                {content_data['description'][:1000]}{'...' if len(content_data['description']) > 1000 else ''}
            
                Transcript:
                {transcript[:2000]}{'...' if len(transcript) > 2000 else ''}
            
                Provide a comprehensive analysis with structured output.
            """

            # it was:
            # analysis_agent = self.analysis_agent
            # result = await analysis_agent.run(analysis_prompt)
            result = await self.analysis_agent.run(analysis_prompt)

            self.logger.info(f"Analysis result: {result.output}")
            return result.output

        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Content analysis failed with OpenRouter: {error_msg}")

            # Handle specific OpenRouter errors
            if any(
                keyword in error_msg.lower()
                for keyword in ["quota", "rate limit", "insufficient_quota", "429"]
            ):
                self.logger.warning(
                    "OpenRouter quota or rate limit exceeded. Consider upgrading your plan or switching models."
                )
            elif any(
                keyword in error_msg.lower() for keyword in ["authentication", "api key", "401"]
            ):
                self.logger.error(
                    "Authentication failed for OpenRouter. Please check your API key configuration."
                )

            # Return default structured result on failure
            return ContentAnalysisResult(
                topics=[],
                sentiment="neutral",
                locations=[],
                key_insights=[],
                content_category="general",
            )
