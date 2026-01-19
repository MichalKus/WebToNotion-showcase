"""Notion Mapper Agent.

This module defines the PydanticAI agent responsible for mapping video content
to a specific Notion database schema. It uses the schema as a strict guide
to generate a valid Notion page payload.
"""

from typing import Any, Dict

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from webtonotion.config.settings import settings


# Define the agent with a specific model (e.g., GPT-4o for complex reasoning)
# We use a dependency to inject the schema at runtime
class MapperDependencies:
    schema: Dict[str, Any]
    database_id: str


# Initialize OpenRouter model using settings
# Ensure API key is available
if not settings.openrouter_api_key:
    raise ValueError("OpenRouter API key is required for Notion Mapper Agent")

model = OpenRouterModel(
    settings.openrouter_model,
    provider=OpenRouterProvider(api_key=settings.openrouter_api_key),
)

notion_mapper_agent = Agent(
    model,
    deps_type=MapperDependencies,
    system_prompt=(
        "You are an expert Notion API integrator. Your task is to map video content information"
        "to a Notion database schema.\n\n"
        "Input:\n"
        "1. Video Content: Structured data about a video (title, transcript, sentiment, etc.).\n"
        "2. Database Schema: The exact structure of the target Notion database (provided in context).\n"
        "3. Database ID: The ID of the target database (provided in context).\n\n"
        "Rules:\n"
        "- You MUST return clean, valid JSON only. \n"
        "- STRICTLY FORBIDDEN: Do NOT wrap the output in markdown code blocks (e.g., ```json ... ```).\n"
        "- Do NOT add any text before or after the JSON object.\n"
        "- The output must start with `{` and end with `}`.\n"
        "- The `parent` field must be `{'database_id': '<provided_db_id>'}`.\n"
        "- The `properties` dictionary MUST strictly follow the provided Database Schema.\n"
        "  - Keys in `properties` must match the property names in the schema exactly (case-sensitive).\n"
        "  - Values must be the correct format for that property type.\n"
        "- Do NOT include properties that are automatically filled by Notion. SKIP properties with these types in the schema:\n"
        "  - `created_time`\n"
        "  - `last_edited_time`\n"
        "  - `created_by`\n"
        "  - `last_edited_by`\n"
        "  - `formula`\n"
        "  - `rollup`\n"
        "  - `unique_id`\n"
        "  - `verification`\n"
        "- Map video fields to database properties intelligently:\n"
        "  - If a property is for example named 'Status' (Select), infer the status (e.g., 'To Watch', 'Done').\n"
        "  - If a property exists in the schema but not in the video object, try to infer it from the transcript or leave it empty if impossible.\n"
        "- Construct the page content (`children`) to be a useful summary of the video:\n"
        "  - Start with a Heading 1 for the title.\n"
        "  - Add a Paragraph for the summary.\n"
        "  - If 'Key Points' or similar exist in the video data, use a Bulleted List.\n"
        "  - If 'Locations' are mentioned, list them.\n"
        "- Do NOT hallucinate property names that are not in the schema."
    ),
)


@notion_mapper_agent.system_prompt
def add_schema_to_prompt(ctx: RunContext[MapperDependencies]) -> str:
    """Dynamic system prompt to inject the specific database schema."""
    return (
        f"Target Database ID: {ctx.deps.database_id}\n"
        f"Target Database Schema: {ctx.deps.schema}\n"
    )
