# Notion Integration

The hard part of writing to Notion is that the target database is **user-defined**. One
person's database calls the link column `URL`, another calls it `Link`, a third has a
`Status` select with options that don't exist anywhere else. A static field mapping breaks
on the second user.

WebToNotion solves this by combining a deterministic schema fetch with an AI mapping step:

1. **Fetch** the exact database schema from the Notion API.
2. **Inject** that schema into a PydanticAI agent's instructions.
3. **Validate** the agent's output against the schema, retrying on mismatch.
4. **Create** the page with the validated payload.

The AI never guesses what properties exist — it is told, and then checked.

All four steps live in `agents/writer.py` (`build_page_content` assembles the input,
`write_video_page` runs the mapper and creates the page). Both `POST /api/v1/process/url`
and the chat `save_to_notion` tool call it — the Notion write is defined once.
`NotionService` itself is a pure Notion API client: `get_databases`, `create_page`,
`get_database_properties`, `health_check`. It no longer imports the mapper agent or any
video model.

## Fetching the schema

`NotionService.get_database_properties` is a two-hop call, because Notion API version
`2025-09-03` moved properties behind data sources:

```python
database_details = client.databases.retrieve(database_id)
data_source_id = database_details["data_sources"][0]["id"]
properties = client.data_sources.retrieve(data_source_id)["properties"]
```

Only the **first** data source is read. A database with multiple data sources will map
against the first one only.

This call also doubles as an access check — it runs before any video work, so a database
the integration hasn't been shared with fails fast with 401.

## The mapper agent

`services/analysis/notion_mapper.py` builds the mapper agent through
`build_mapper_agent(settings)` — a factory wrapping an `@lru_cache`d inner keyed on
`(model_name, api_key, retries)`, the same pattern every other agent in the repo uses. There
is **no `notion_mapper_agent` module global**; nothing constructs an `OpenRouterModel` at
import time. The agent has `output_type=PromptedOutput(NotionPagePayload)` and runs on
`OPENROUTER_MODEL`.

The schema arrives through a dependency, injected by dynamic instructions registered inside
the factory:

```python
@dataclass
class MapperDependencies:
    schema: Dict[str, Any]
    database_id: str

def add_schema_to_prompt(ctx: RunContext[MapperDependencies]) -> str:
    return (
        f"Target Database ID: {ctx.deps.database_id}\n"
        f"Target Database Schema: {ctx.deps.schema}\n"
    )
# ... inside build_mapper_agent:
#   agent.instructions(add_schema_to_prompt)
#   agent.output_validator(validate_notion_payload)
```

`add_schema_to_prompt` and `validate_notion_payload` are module-level plain functions now,
registered on the agent when the factory builds it rather than via decorators at import.

The static half of the instructions teaches the agent the Notion property-value grammar —
how `title`, `rich_text`, `select`, `multi_select`, `date`, `number`, and `url` values are
shaped, which block types are valid children, and which property types to skip because
Notion computes them itself (`formula`, `rollup`, `created_time`, `last_edited_time`,
`created_by`, `last_edited_by`, `unique_id`, `verification`).

Rather than enumerating every Notion type, the prompt teaches a general rule — wrap the
value in an object keyed by the schema's `type` field, and look at the type's config object
for structure hints. That keeps the prompt working against property types it was never
explicitly shown.

## Validation and retry

The output validator is where correctness is actually enforced:

```python
async def validate_notion_payload(ctx, output: NotionPagePayload) -> NotionPagePayload:
    ...
# registered by the factory: agent.output_validator(validate_notion_payload)
```

It raises `ModelRetry` — which sends the error back to the model for another attempt,
bounded by `MAX_RETRIES` — when:

1. `parent.database_id` doesn't match the target database.
2. A property name isn't in the schema. The retry message lists the available names.
3. A property's value object lacks a key matching its schema `type` (e.g. a property typed
   `select` whose value has no `select` key).

This is the mechanism that makes an unreliable generator reliable: a hallucinated column
name doesn't reach Notion, it comes back as a correction.

## Creating the page

`agents/writer.write_video_page` filters the mapper's payload before handing it to
`NotionService.create_page`:

```python
properties = {k: v for k, v in page_payload.properties.items() if v}
```

Empty values are dropped because Pydantic's `exclude_none` can leave bare `{}` for optional
fields like `select` and `date`, which Notion rejects outright.

The `children` blocks are passed through as-is and become the page body. `write_video_page`
returns a `SaveResult` (`page_id`, `page_url`, `database_id`, `title`); a mapper failure is
wrapped as `ContentProcessingError` (→ HTTP 500), while `create_page` errors
(`NotionAuthenticationError` → 401, `NotionAPIError` → 503) propagate untouched.

## Payload shape

`NotionPagePayload` (`models/notion.py`):

```python
class NotionPagePayload(BaseModel):
    parent: Dict[str, str]          # {"database_id": "..."}
    properties: Dict[str, Any]      # keyed by schema property name
    children: List[Dict[str, Any]]  # page content blocks
```

A representative result:

```json
{
  "parent": {"database_id": "abc123"},
  "properties": {
    "Name":   {"title": [{"text": {"content": "Python Tutorial"}}]},
    "URL":    {"url": "https://youtube.com/watch?v=123"},
    "Tags":   {"multi_select": [{"name": "Programming"}, {"name": "Beginner"}]},
    "Status": {"select": {"name": "To Watch"}}
  },
  "children": [
    {"object": "block", "type": "heading_1",
     "heading_1": {"rich_text": [{"text": {"content": "Python Tutorial"}}]}}
  ]
}
```

Exactly one `title` property is required per page.

## Rate limiting and errors

`NotionService` holds its own `RateLimiter(max_requests=3, time_window=1)`, matching
Notion's documented 3 req/s ceiling. It applies to `get_databases`, `create_page`,
`get_database_properties`, and `health_check`.

`_handle_api_error` maps `notion-client` exceptions to the application hierarchy:

| Notion condition | Raised | HTTP |
|---|---|---|
| 401 | `NotionAuthenticationError` | 401 |
| 429 | `NotionRateLimitError` | 500 (not specially handled in the router) |
| Other `APIResponseError` | `NotionAPIError` | 503 |
| Timeout / HTTP error | `NotionAPIError` | 503 |

## Constraints

- A transcript excerpt (up to `_TRANSCRIPT_EXCERPT_CHARS`, currently 4000) plus the title,
  description, and any cached summary are what `build_page_content` sends to the mapper.
- One OpenRouter call happens per `/process/url` request — the mapper. There is no separate
  content-analysis call any more.
- The mapper is prompt-driven, so upgrading `OPENROUTER_MODEL` changes mapping quality.
  Weaker models fail the output validator more often, consuming retries.
- Do not mock the payload shape in tests. Construct `NotionPagePayload` directly so schema
  changes surface as test failures.
