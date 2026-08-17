"""Notion Mapper Agent.

This module defines the PydanticAI agent responsible for mapping video content
to a specific Notion database schema. It uses the schema as a strict guide
to generate a valid Notion page payload.
"""

from dataclasses import dataclass
from typing import Any, Dict

from pydantic_ai import Agent, ModelRetry, PromptedOutput, RunContext
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.settings import ModelSettings

from webtonotion.config.settings import settings
from webtonotion.models.notion import NotionPagePayload


# Define the agent with a specific model (e.g., GPT-4o for complex reasoning)
# We use a dependency to inject the schema at runtime
@dataclass
class MapperDependencies:
    schema: Dict[str, Any]
    database_id: str


# Initialize OpenRouter model using settings.
model = OpenRouterModel(
    settings.openrouter_model,
    provider=OpenRouterProvider(api_key=settings.openrouter_api_key or "unset"),
)

notion_mapper_agent = Agent(
    model,
    deps_type=MapperDependencies,
    output_type=PromptedOutput(NotionPagePayload),
    retries=settings.max_retries,
    system_prompt="""You are a Notion API specialist. Map video content to Notion database properties.

        ## Your Task
        Transform video metadata into a valid Notion page payload that matches the provided database schema exactly.

        ## Core Principles
        1. Use ONLY property names that exist in the provided schema (case-sensitive match required)
        2. Match the exact data type format for each property type
        3. Skip auto-generated properties: formula, rollup, created_time, last_edited_time, created_by, last_edited_by, unique_id, verification
        4. Set parent to {'database_id': '<provided_database_id>'}

        ## Property Type Formats
        Each property in the schema has a `type` field. Follow this universal pattern:

        **Basic Structure:**
        {"PropertyName": {"type_from_schema": <value>}}

        **How to determine the correct value:**

        1. **Examine the schema**: Each property has a nested object matching its type name (e.g., if `"type": "select"`, there will be a `"select": {...}` object)

        2. **Look for configuration clues**:
           - If you see an `options` array → value must reference option names from that array using `{"name": "OptionName"}` structure
           - If you see `groups` with options → similar to options, reference valid names
           - If the type name contains "text" → likely uses array format: `[{"text": {"content": "..."}}]`
           - If it's a simple data type → likely a primitive value or simple wrapper

        3. **Special notes**:
           - Exactly ONE property with type `title` is required per page
           - For types with options (select, multi_select, status), validate option names against the schema
           - Null values are acceptable for optional properties

        **When encountering unfamiliar types:**
        - Check the schema's type-specific configuration object for structure hints
        - Apply the pattern: wrap your value in an object keyed by the type name
        - Look for similar patterns in the schema reference

        ## Content Block Formats
        Build the children array with these block types:

        **Heading**:
        {"object": "block", "type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "Title"}}]}}

        **Paragraph**:
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "Text"}}]}}

        **Bullet point**:
        {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "Point"}}]}}

        **Numbered item**:
        {"object": "block", "type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"text": {"content": "Step"}}]}}

        ## Mapping Strategy
        1. Find the title property in the schema → map video title to it
        2. For each remaining schema property, check if video data contains relevant information
        3. If video has matching data, format it according to the property type
        4. If video lacks data for a property, omit that property from the output
        5. Use video transcript to infer appropriate values for Status, Tags, or Category properties when present in schema
        6. For select/multi_select/status properties, check the schema's options array and use ONLY valid option names

        ## Example Mapping
        Given video data:
        {"title": "Python Tutorial", "url": "https://youtube.com/watch?v=123", "tags": ["Programming", "Beginner"]}

        And schema with properties: "Name" (title), "URL" (url), "Tags" (multi_select), "Status" (select)

        Correct output:
        {
          "parent": {"database_id": "abc123"},
          "properties": {
            "Name": {"title": [{"text": {"content": "Python Tutorial"}}]},
            "URL": {"url": "https://youtube.com/watch?v=123"},
            "Tags": {"multi_select": [{"name": "Programming"}, {"name": "Beginner"}]},
            "Status": {"select": {"name": "To Watch"}}
          },
          "children": [
            {"object": "block", "type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "Python Tutorial"}}]}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "Educational programming content for beginners"}}]}}
          ]
        }
        """,
)


@notion_mapper_agent.system_prompt
def add_schema_to_prompt(ctx: RunContext[MapperDependencies]) -> str:
    """Dynamic system prompt to inject the specific database schema."""
    return (
        f"Target Database ID: {ctx.deps.database_id}\n"
        f"Target Database Schema: {ctx.deps.schema}\n"
    )


@notion_mapper_agent.output_validator
async def validate_notion_payload(
    ctx: RunContext[MapperDependencies], output: NotionPagePayload
) -> NotionPagePayload:
    """Validate that the generated payload strictly matches the Notion schema.

    This validator checks:
    1. Parent database ID matches the target.
    2. All property names exist in the target schema.
    3. Each property value format matches the expected Notion type.
    """
    # 1. Validate parent database ID
    if output.parent.get("database_id") != ctx.deps.database_id:
        raise ModelRetry(
            f"Incorrect database_id in parent field. Must be exactly '{ctx.deps.database_id}'"
        )

    # 2. Validate properties against schema
    schema_properties = ctx.deps.schema

    for prop_name, prop_value in output.properties.items():
        # Check if property exists in schema
        if prop_name not in schema_properties:
            available = ", ".join(schema_properties.keys())
            raise ModelRetry(
                f"Property '{prop_name}' does not exist in the target database schema. "
                f"Available properties are: {available}"
            )

        # Check if property format matches expected type
        expected_type = schema_properties[prop_name].get("type")
        if expected_type and expected_type not in prop_value:
            # For some types, Notion uses a slightly different key than the type name,
            # but for most standard ones (title, rich_text, select, etc.) they match.
            # We enforce matching the 'type' key from the schema.
            raise ModelRetry(
                f"Property '{prop_name}' is of type '{expected_type}' in the schema, "
                f"but the output format is incorrect. Expected key '{expected_type}' in the property object."
            )

    return output
