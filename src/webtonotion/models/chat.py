"""Chat and agent tool data models.

This module defines the Pydantic models for the agentic chat surface: the
request/response envelope for ``/api/v1/chat`` and the small, chat-sized return
types the orchestrator tools produce. Every tool returns one of these rather than
free text or a large payload, so conversation history stays compact.
"""

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


class ChatReply(BaseModel):
    """Outgoing chat reply.

    Attributes:
        session_id: The session the turn was recorded against.
        reply: The assistant's natural-language reply.
        confirmed_database_id: The session's confirmed write target, if any.
        trace: Chronological steps of this turn — reasoning, tool calls and their
            results, and any intermediate text — for clients that want to show why
            the agent acted, not just its final answer.
    """

    session_id: str = Field(..., description="Session identifier for this turn")
    reply: str = Field(..., description="Assistant reply text")
    confirmed_database_id: str | None = Field(
        default=None, description="Confirmed target database id, or null if unset"
    )
    trace: list[TraceStep] = Field(
        default_factory=list, description="Chronological reasoning/tool-call trace for this turn"
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
