<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# I have a pydantic ai agent that for now is mapping video informations to a proper notion database fields and return proper json schema that will be used to create a page in notion. Unfotunately it is not always doing alright and sometimes it is generating wrong json (wrong schema or missing field or wrong field name). Give me 5 best strategies how I can improve this agent work so it will always prepare a proper structure that can be used to create a page with notion api. Remember to check also pydantic ai library tips and tricks that we can use.

Based on your code and PydanticAI best practices, here are 5 strategies to significantly improve your Notion mapper agent's reliability:

## 1. Use Structured Output Types with Pydantic Models

Replace your current string-based JSON output with strongly-typed Pydantic models. This leverages PydanticAI's tool-calling capability to enforce the schema automatically:[^1][^2]

```python
from pydantic import BaseModel, Field
from typing import Any, Dict, List

class NotionProperty(BaseModel):
    """Base for Notion property values"""
    pass

class NotionPagePayload(BaseModel):
    """Structured output for Notion page creation"""
    parent: Dict[str, str] = Field(description="Must contain database_id")
    properties: Dict[str, Any] = Field(
        description="Properties matching the exact Notion database schema"
    )
    children: List[Dict[str, Any]] = Field(
        description="Page content blocks (heading_1, paragraph, bulleted_list_item)"
    )

notion_mapper_agent = Agent(
    model,
    deps_type=MapperDependencies,
    output_type=NotionPagePayload,  # Enforce structure via tool calling
    system_prompt="..."
)
```

This ensures the model returns valid JSON matching your schema, as PydanticAI uses the model's tool-calling API to guarantee structural compliance.[^2][^1]

## 2. Implement Output Validators with ModelRetry

Add validation logic that checks against the actual Notion schema and retries on mismatches:[^1][^2]

```python
from pydantic_ai import ModelRetry, RunContext

@notion_mapper_agent.output_validator
async def validate_notion_schema(
    ctx: RunContext[MapperDependencies], 
    output: NotionPagePayload
) -> NotionPagePayload:
    """Validate output matches Notion database schema exactly"""
    
    if ctx.partial_output:  # Skip validation for streaming partial outputs
        return output
    
    schema = ctx.deps.schema
    
    # Validate parent field
    if output.parent.get('database_id') != ctx.deps.database_id:
        raise ModelRetry(
            f"Parent database_id must be '{ctx.deps.database_id}'"
        )
    
    # Validate all property keys exist in schema
    schema_properties = schema.get('properties', {})
    for prop_name in output.properties.keys():
        if prop_name not in schema_properties:
            raise ModelRetry(
                f"Property '{prop_name}' not found in schema. "
                f"Available properties: {list(schema_properties.keys())}"
            )
    
    # Validate property types match schema
    for prop_name, prop_value in output.properties.items():
        expected_type = schema_properties[prop_name].get('type')
        if not _validate_property_type(prop_value, expected_type):
            raise ModelRetry(
                f"Property '{prop_name}' has incorrect format for type '{expected_type}'"
            )
    
    return output
```

Output validators allow complex async validation and use `ModelRetry` to automatically ask the model to correct errors.[^2][^1]

## 3. Add Union Types with Failure Modes

Implement a union output type that allows the agent to explicitly signal when it cannot map the data properly:[^3]

```python
from pydantic import BaseModel

class NotionMappingSuccess(BaseModel):
    """Successfully mapped video to Notion page"""
    parent: Dict[str, str]
    properties: Dict[str, Any]
    children: List[Dict[str, Any]]

class NotionMappingFailure(BaseModel):
    """Unable to map video data to schema"""
    reason: str = Field(
        description="Explanation of why mapping failed"
    )
    missing_fields: List[str] = Field(
        description="Required schema fields that couldn't be mapped"
    )
    conflicting_types: List[str] = Field(
        default_factory=list,
        description="Properties where video data type conflicts with schema"
    )

Output = NotionMappingSuccess | NotionMappingFailure

notion_mapper_agent = Agent[MapperDependencies, Output](
    model,
    deps_type=MapperDependencies,
    output_type=Output,  # type: ignore
    system_prompt="Your task is to map video content to Notion schema. "
                  "If you cannot properly map all required fields, "
                  "use NotionMappingFailure to explain why."
)
```

This prevents the agent from hallucinating fields or forcing invalid mappings when it lacks sufficient information.[^3]

## 4. Leverage Field Descriptions in Pydantic Models

Use comprehensive `Field` descriptions to guide the model's output generation:[^1][^3]

```python
class NotionPagePayload(BaseModel):
    parent: Dict[str, str] = Field(
        description="Parent reference - MUST be {'database_id': '<database_id>'}"
    )
    properties: Dict[str, Any] = Field(
        description=(
            "Property values matching schema exactly. "
            "Key names must match schema property names (case-sensitive). "
            "Common types: "
            "- title: {'title': [{'text': {'content': 'text'}}]} "
            "- rich_text: {'rich_text': [{'text': {'content': 'text'}}]} "
            "- select: {'select': {'name': 'option_name'}} "
            "- multi_select: {'multi_select': [{'name': 'option1'}]} "
            "- date: {'date': {'start': 'YYYY-MM-DD'}} "
            "- number: {'number': 123} "
            "- url: {'url': 'https://...'}"
        )
    )
    children: List[Dict[str, Any]] = Field(
        description=(
            "Page content blocks. Valid block types: "
            "heading_1, heading_2, heading_3, paragraph, "
            "bulleted_list_item (NOT bulleted_list), "
            "numbered_list_item (NOT numbered_list). "
            "Each block: {'object': 'block', 'type': '<type>', '<type>': {'rich_text': [...]}}"
        )
    )
```

Field descriptions are automatically included in the schema sent to the model, serving as inline documentation.[^2][^1]

## 5. Implement Retry Configuration and Result Validation

Configure automatic retries and add post-processing validation:[^4]

```python
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior

notion_mapper_agent = Agent(
    model,
    deps_type=MapperDependencies,
    output_type=NotionPagePayload,
    retries=3,  # Automatically retry on validation failures
    system_prompt="..."
)

async def map_video_to_notion(video_data: Dict, schema: Dict, database_id: str):
    deps = MapperDependencies(schema=schema, database_id=database_id)
    
    try:
        result = await notion_mapper_agent.run(
            f"Map this video data to Notion: {video_data}",
            deps=deps
        )
        
        # Additional validation after agent returns
        payload = result.output
        
        # Verify required Notion fields
        if 'parent' not in payload.__dict__:
            raise ValueError("Missing 'parent' field")
        if 'properties' not in payload.__dict__:
            raise ValueError("Missing 'properties' field")
            
        return payload.model_dump()
        
    except UnexpectedModelBehavior as e:
        # Log and handle agent failures
        print(f"Agent failed after retries: {e}")
        raise
```

PydanticAI automatically retries when `ModelRetry` is raised, and you can configure the maximum retry attempts.[^4][^1]

***

These strategies transform your agent from prompt-based JSON generation to a type-safe, validated system with explicit error handling. The combination of structured outputs, validation, and failure modes will dramatically reduce incorrect schema generation.[^3][^1][^2]
<span style="display:none">[^10][^11][^5][^6][^7][^8][^9]</span>

<div align="center">⁂</div>

[^1]: notion_mapper.py

[^2]: https://ai.pydantic.dev/output/

[^3]: https://realm.security/embracing-uncertainty-with-ai-agents-vulnerability-assessment-using-pydantic-ai/

[^4]: https://www.prefect.io/blog/prefect-pydantic-integration

[^5]: https://community.openai.com/t/how-to-use-a-single-pydantic-model-for-structured-output-with-long-documents-in-a-chunked-rag-pipeline/1080681

[^6]: https://docs.swarms.world/en/latest/swarms/examples/pydantic_structured_outputs_tutorial/

[^7]: https://codesignal.com/learn/courses/getting-started-with-openai-agents-in-python/lessons/structuring-agent-outputs-with-the-outputtype-parameter-and-pydantic

[^8]: https://community.openai.com/t/structured-output-precision-accuracy-pydantic-vs-a-schema/1054410

[^9]: https://ai.pydantic.dev/api/result/

[^10]: http://oreateai.com/blog/implementing-structured-processing-of-llm-outputs-using-pydantic/f33a2de6bcfa7c0d9fc69e7ca1429cf8

[^11]: https://ai.pydantic.dev/durable_execution/overview/

