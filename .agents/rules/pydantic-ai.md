---
trigger: glob
globs: src/webtonotion/services/analysis/**/*.py, tests/**/test_*analy*.py, tests/**/test_*mapper*.py
description: PydanticAI agent conventions — where agents live, how they are configured against OpenRouter, and how to test them without calling a model.
---

# PydanticAI conventions

Agent code lives in `src/webtonotion/services/analysis/`. There is no `src/ai/` or
`src/agents/` package — do not create one.

- `content_analyzer.py` — `ContentAnalyzer`, topic/sentiment/location/insight extraction.
- `notion_mapper.py` — `notion_mapper_agent`, maps a `VideoContent` onto a Notion schema.
- Agent output models live in `src/webtonotion/models/` (`video.py`, `notion.py`), never
  beside the agent.

## Configuring an agent

Every agent goes through OpenRouter, keyed from settings — never a bare `"openai:gpt-4o"`
string:

```python
from pydantic_ai import Agent
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from webtonotion.config.settings import settings
from webtonotion.models.video import ContentAnalysisResult

model = OpenRouterModel(
    settings.openrouter_model,
    provider=OpenRouterProvider(api_key=settings.openrouter_api_key),
)

agent = Agent(
    model,
    output_type=ContentAnalysisResult,
    retries=settings.max_retries,
    system_prompt="…",
)
```

- Always give `output_type` a Pydantic model. Never parse free text out of a response.
- `retries` comes from `settings.max_retries` — retry counts are centralised, not literals.
- Use `PromptedOutput(Model)` when the schema is too large or dynamic for tool-based
  structured output; `notion_mapper.py` does this for `NotionPagePayload`.
- Reach the result via `result.output`.

## Runtime dependencies

Inject per-run context with a dataclass and `deps_type` rather than hardcoding or
constructing state inside the agent:

```python
@dataclass
class MapperDependencies:
    schema: Dict[str, Any]
    database_id: str

agent = Agent(model, deps_type=MapperDependencies, output_type=…)

@agent.system_prompt
def add_schema(ctx: RunContext[MapperDependencies]) -> str:
    return f"Target database: {ctx.deps.database_id}"
```

## Validation and self-correction

- Output models use Pydantic **v2** validators — `@field_validator` / `@model_validator`.
  `@validator` is v1 and is removed.
- Inside an output validator or tool, raise `ModelRetry("what was wrong")` to hand the model
  a correction instead of failing the request outright.
- Constrain fields where the domain allows it (`Literal["positive", "negative", "neutral"]`,
  `Field(ge=0, le=1)`) — a constrained type beats a validator that re-checks a string.

## Async

Agents are awaited: `result = await agent.run(prompt)`. Never call `run_sync()` from async
request-handling code. Do not wrap an `async def` in `functools.lru_cache` — it caches the
coroutine object, not the value.

## Testing

Never call a real model in `tests/unit/`. Override the model instead of mocking internals:

```python
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

models.ALLOW_MODEL_REQUESTS = False  # module level: fails loudly on any real request

async def test_analysis():
    with agent.override(model=TestModel()):
        result = await agent.run("…")
    assert result.output.sentiment == "neutral"
```

- Use `FunctionModel` when the test needs to script the response or assert on what the agent
  sent; `capture_run_messages()` when it needs the full message exchange.
- Override dependencies with `agent.override(deps=…)`.
- `MagicMock(spec=AgentRunResult)` is not the way — it tests the mock, not the agent.
- Tests that intentionally hit a live model belong in `tests/integration/` and will be
  auto-marked `requires_api_keys`.

## Observability

`logfire.instrument_pydantic_ai()` is already called in `config/logging.py`; runs are traced
automatically. Do not add ad-hoc `logfire.log` calls around every agent invocation, and never
log a full transcript or API key.

## Prompts

System prompts are defined in the module that owns the agent (a `_get_system_prompt()` method
or the `system_prompt=` argument). There is no external prompt registry — `langfuse` is not a
dependency of this project.
