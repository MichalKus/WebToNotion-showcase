"""Chat and agent tool data models.

This module defines the Pydantic models for the agentic chat surface: the
request/response envelope for ``/api/v1/chat`` and the small, chat-sized return
types the orchestrator tools produce. Every tool returns one of these rather than
free text or a large payload, so conversation history stays compact.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """Incoming chat message.

    Attributes:
        message: The user's natural-language message.
        conversation_id: Stable id grouping messages of one conversation.
        session_id: Existing session to continue; omitted to start a new one.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "find me a database to save videos to",
                "conversation_id": "c1",
            }
        }
    )

    message: str = Field(..., min_length=1, description="User message text")
    conversation_id: str = Field(..., min_length=1, description="Conversation identifier")
    session_id: str | None = Field(
        default=None, description="Session to continue (new session created if omitted)"
    )


class TraceStep(BaseModel):
    """One step of an orchestrator run: reasoning, a tool call, its result, or reply text.

    Built from ``result.new_messages()`` for just the turn that produced a
    ``ChatReply``, in chronological order, so a client can see why the agent did
    what it did without querying Logfire or replaying the raw session history.
    """

    kind: Literal["thinking", "tool_call", "tool_return", "text"] = Field(
        ..., description="What kind of step this is"
    )
    tool: str | None = Field(
        default=None, description="Tool name, present on tool_call/tool_return steps"
    )
    args: dict[str, Any] | str | None = Field(
        default=None, description="Tool call arguments, present on tool_call steps"
    )
    content: Any | None = Field(
        default=None,
        description="Thinking text, the tool's return value, or reply text, depending on kind",
    )


class UsageSummary(BaseModel):
    """Model usage for one chat turn, across the orchestrator and any sub-agent runs.

    Sub-agent runs (``summarize``/``ask_about_video``) share the orchestrator's
    ``RunContext.usage``, so this reflects the whole turn's cost, not just the
    orchestrator's own requests.
    """

    requests: int = Field(..., description="Total model requests made during the turn")
    input_tokens: int = Field(..., description="Total input tokens across all requests")
    output_tokens: int = Field(..., description="Total output tokens across all requests")
    total_tokens: int = Field(..., description="input_tokens + output_tokens")
    cost: float | None = Field(
        default=None, description="Estimated cost in USD, when the provider reports one"
    )


class ChatReply(BaseModel):
    """Outgoing chat reply.

    Attributes:
        session_id: The session the turn was recorded against.
        reply: The assistant's natural-language reply.
        confirmed_database_id: The session's confirmed write target, if any.
        trace: Chronological steps of this turn — reasoning, tool calls and their
            results, and any intermediate text — for clients that want to show why
            the agent acted, not just its final answer.
        usage: Model usage for the turn, including any sub-agent runs.
    """

    session_id: str = Field(..., description="Session identifier for this turn")
    reply: str = Field(..., description="Assistant reply text")
    confirmed_database_id: str | None = Field(
        default=None, description="Confirmed target database id, or null if unset"
    )
    trace: list[TraceStep] = Field(
        default_factory=list, description="Chronological reasoning/tool-call trace for this turn"
    )
    usage: UsageSummary | None = Field(
        default=None, description="Model usage for the turn, including sub-agent runs"
    )


class DatabaseCandidate(BaseModel):
    """A ranked Notion database proposed as a write target."""

    id: str = Field(..., description="Notion database id")
    name: str = Field(..., description="Database title")
    key_properties: list[str] = Field(
        default_factory=list, description="A few distinguishing property names"
    )


class SchemaInfo(BaseModel):
    """The inspected schema of a single Notion database."""

    database_id: str = Field(..., description="Notion database id")
    properties: dict[str, str] = Field(
        default_factory=dict, description="Property name -> Notion property type"
    )
    select_options: dict[str, list[str]] = Field(
        default_factory=dict, description="Property name -> allowed select/multi-select options"
    )


class WriteBlocked(BaseModel):
    """Structured refusal returned by ``save_to_notion`` when no target is confirmed.

    This is a normal tool return value, never an exception: the agent sees it and
    responds by proposing databases and asking the user, rather than aborting the run.
    """

    reason: str = Field(..., description="Why the write was blocked")
    candidates: list[DatabaseCandidate] = Field(
        default_factory=list, description="Suggested databases to confirm"
    )


class ToolError(BaseModel):
    """A recoverable tool failure the agent can see, explain, and work around."""

    reason: str = Field(..., description="Short failure reason")
    detail: str | None = Field(default=None, description="Optional additional detail")


class SaveResult(BaseModel):
    """Success return of `save_to_notion` and the shared write path.

    Attributes:
        page_id: The Notion page ID of the created/updated page
        page_url: The full URL to the created/updated Notion page
        database_id: The Notion database ID the page was saved to
        title: The title of the saved page
    """

    page_id: str = Field(..., description="Notion page ID of the created/updated page")
    page_url: str = Field(..., description="Full URL to the Notion page")
    database_id: str = Field(..., description="Notion database ID where the page was saved")
    title: str = Field(..., description="Title of the saved page")


class VideoMetadata(BaseModel):
    """Chat-sized video metadata returned by ``get_video_metadata``."""

    url: str = Field(..., description="Video URL")
    title: str = Field(..., description="Video title")
    author: str = Field(default="", description="Creator or channel name")
    duration: float | None = Field(default=None, description="Duration in seconds", ge=0)
    platform: str = Field(default="unknown", description="Source platform, e.g. 'youtube'")
    published_at: datetime | None = Field(default=None, description="Publication timestamp")


SummaryStyle = Literal[
    "concise",
    "bullet points",
    "detailed",
    "for a beginner",
    "key takeaways",
]

SummaryLength = Literal["short", "medium", "long"]


class SummaryResult(BaseModel):
    """A summary of one video, produced by an ephemeral sub-agent run."""

    url: str = Field(..., description="Video URL the summary describes")
    style: SummaryStyle = Field(
        ...,
        description="Requested style: 'concise', 'bullet points', 'detailed', 'for a beginner', or 'key takeaways'",
    )
    length: SummaryLength = Field(..., description="Requested length: 'short', 'medium', or 'long'")
    summary: str = Field(..., description="The summary text")


class AnswerResult(BaseModel):
    """An answer to a question about one video, plus the excerpts it rests on."""

    url: str = Field(..., description="Video URL the answer is about")
    question: str = Field(..., description="The question asked")
    answer: str = Field(..., description="The answer text")
    excerpts: list[str] = Field(
        default_factory=list, description="Timestamped transcript excerpts supporting the answer"
    )


class AnswerAttempt(BaseModel):
    """Structured output of the answering sub-agent.

    ``sufficient`` is the escalation signal: a first pass runs against the compact
    context (cached summary plus a timestamped segment index); when the sub-agent
    reports the context was not enough, the caller re-runs it against the full
    transcript. Most follow-up questions never need the raw text.
    """

    answer: str = Field(..., description="Best answer from the context provided")
    sufficient: bool = Field(
        ..., description="Whether the provided context was enough to answer confidently"
    )
    excerpts: list[str] = Field(
        default_factory=list, description="Quoted excerpts, timestamped where available"
    )
