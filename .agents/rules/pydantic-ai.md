---
trigger: glob
globs: src/webtonotion/services/analysis/**/*.py, src/webtonotion/agents/**/*.py, src/webtonotion/models/chat.py, tests/**/test_*analy*.py, tests/**/test_*mapper*.py, tests/**/test_*agent*.py, tests/**/test_*session*.py
description: PydanticAI agent conventions — where agents live, how they are configured against OpenRouter, instructions vs system prompts, multi-turn/orchestrator agents, and how to test them without calling a model.
---

# PydanticAI conventions

Two kinds of agent live in this repo, and they have different needs:

- **One-shot analysis agents** in `src/webtonotion/services/analysis/` — one prompt in, one
  structured object out, no conversation.
  - `content_analyzer.py` — `ContentAnalyzer`, topic/sentiment/location/insight extraction.
  - `notion_mapper.py` — `notion_mapper_agent`, maps a `VideoContent` onto a Notion schema.
- **Multi-turn orchestrator agents** in `src/webtonotion/agents/` — chat sessions that span
  several runs and carry message history between them (see the orchestrator spec).

Agent output models live in `src/webtonotion/models/` (`video.py`, `notion.py`, `chat.py`),
never beside the agent. Do not create an `src/ai/` package — agents live in the two
locations above.

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
    instructions="…",  # not system_prompt — see below
)
```

- `OpenRouterModel` / `OpenRouterProvider` are the correct, dedicated classes — OpenRouter is
  **not** just `OpenAIChatModel`, so keep these imports. The `"openrouter:<model>"` string form
  exists but we use the explicit form so the API key comes from `settings`.
- Instantiate an agent **once** at module level and reuse it, like a FastAPI app or router —
  do not build a new `Agent` per request.
- Always give `output_type` a Pydantic model. Never parse free text out of a response.
- `retries` comes from `settings.max_retries` — retry counts are centralised, not literals.
- Reach the result via `result.output`.

## Type safety

Agents are generic in their dependency and output types: `Agent[DepsType, OutputType]`.
Annotate them that way so `mypy` (which runs strict here — `disallow_untyped_defs`) checks
tool signatures and `output_type` for you:

```python
agent: Agent[MapperDependencies, NotionPagePayload] = Agent(model, deps_type=…, output_type=…)
```

## Instructions, not system prompts

Prefer `instructions` / `@agent.instructions` over `system_prompt` / `@agent.system_prompt`.
They behave identically for a single run, but differ once `message_history` is involved:

- **`instructions`** — when a run is given `message_history`, only the *current* agent's
  instructions are sent; instructions from prior messages are dropped. This is what you want.
- **`system_prompt`** — system prompts from earlier runs are *retained* in the history and
  re-sent every turn. In a multi-turn chat this silently accumulates stale system prompts.

Use `system_prompt` only when you deliberately need that persistence. For everything in this
repo — including the one-shot analysis agents — default to `instructions`.

Static vs dynamic works the same as before: pass `instructions="…"` for static text, or
decorate a function with `@agent.instructions` (optionally taking `RunContext`) for text
computed per run.

## Runtime dependencies

Inject per-run context with a dataclass and `deps_type` rather than hardcoding or
constructing state inside the agent:

```python
@dataclass
class MapperDependencies:
    schema: Dict[str, Any]
    database_id: str

agent = Agent(model, deps_type=MapperDependencies, output_type=…)

@agent.instructions
def add_schema(ctx: RunContext[MapperDependencies]) -> str:
    return f"Target database: {ctx.deps.database_id}"
```

## Structured output

- Default (tool-based) output just takes a Pydantic model in `output_type`.
- `output_type` also accepts a **list/union** of models (`[Fruit, Vehicle]`) when the agent
  may return one of several shapes.
- Wrap the type to change *how* the schema is produced:
  - `PromptedOutput(Model)` — schema goes into the prompt as text. Use when the schema is too
    large or dynamic for tool-based output; `notion_mapper.py` does this for `NotionPagePayload`.
  - `NativeOutput(Model)` — provider-native structured output, for models that support it.
  - `ToolOutput(Model, name=…)` — the default mode, but with a custom tool name.

## Validation and self-correction

- Output models use Pydantic **v2** validators — `@field_validator` / `@model_validator`.
  `@validator` is v1 and is removed.
- Inside an output validator or tool, raise `ModelRetry("what was wrong")` to hand the model
  a correction instead of failing the request outright. Retry budget comes from the agent's
  `retries=` (or per-tool `@agent.tool(retries=N)`); current attempt is `ctx.retry`.
- Constrain fields where the domain allows it (`Literal["positive", "negative", "neutral"]`,
  `Field(ge=0, le=1)`) — a constrained type beats a validator that re-checks a string.

## Tools

Orchestrator agents will register tools; the analysis agents mostly don't. When you add one:

- `@agent.tool` for a tool that needs run context (first arg `ctx: RunContext[Deps]`);
  `@agent.tool_plain` when it doesn't.
- Or pass callables to the constructor: `tools=[roll_dice, Tool(get_name, takes_ctx=True)]`.
- Keep blocking/CPU-bound work off the event loop inside async tools (see the async rule).

## Multi-turn agents (orchestrator)

A single `agent.run(...)` is one **run**; a chat **conversation** is several runs stitched
together by replaying message history.

- Continue a conversation by feeding the previous result's messages into the next run:
  ```python
  result1 = await agent.run("Tell me a joke.")
  result2 = await agent.run("Explain?", message_history=result1.new_messages())
  ```
- `result.new_messages()` = just this run's messages (persist these per turn);
  `result.all_messages()` = the full accumulated history. The `SessionStore` persists and
  replays these, not raw strings.
- Combined with `instructions` (above), only the current agent's instructions are re-sent —
  history stays clean.

### Usage limits

An agentic tool loop can run away. Bound every orchestrator run with `UsageLimits`, which
raises `UsageLimitExceeded`:

```python
from pydantic_ai import UsageLimits

result = await agent.run(
    prompt,
    message_history=history,
    usage_limits=UsageLimits(request_limit=5, tool_calls_limit=10),
)
```

`request_limit` / `tool_calls_limit` cap the loop; `output_tokens_limit` and `cost_limit`
cap spend. Prefer these over ad-hoc counters.

## Async

Agents are awaited: `result = await agent.run(prompt)`. Never call `run_sync()` from async
request-handling code — it belongs in scripts and sync tests only. Do not wrap an `async def`
in `functools.lru_cache` — it caches the coroutine object, not the value.

## Model settings

`ModelSettings` (e.g. `temperature`) can be set at three levels, later overriding earlier:
model (`OpenRouterModel(..., settings=…)`) < agent (`Agent(..., model_settings=…)`) < run
(`agent.run(..., model_settings=…)`). Set it at the agent level for a fixed policy; pass it
per-run only when a specific call needs to differ.

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
- For multi-turn agents, assert on `result.new_messages()` / `result.all_messages()` and feed
  them back through `message_history=` to test a conversation across runs.
- `MagicMock(spec=AgentRunResult)` is not the way — it tests the mock, not the agent.
- Tests that intentionally hit a live model belong in `tests/integration/` and will be
  auto-marked `requires_api_keys`.

## Observability

`logfire.instrument_pydantic_ai()` is already called in `config/logging.py`; runs are traced
automatically. Do not add ad-hoc `logfire.log` calls around every agent invocation, and never
log a full transcript or API key.

## Prompts

Prompts are defined in the module that owns the agent (a `_get_instructions()` method or the
`instructions=` argument). There is no external prompt registry — `langfuse` is not a
dependency of this project.
