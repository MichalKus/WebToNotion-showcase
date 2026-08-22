"""Capability bundles for the orchestrator.

Two concerns live here so the orchestrator wires them in one line each:

- :class:`ProcessHistory` — the history-trim policy. Because tool results are
  small handles rather than payloads, a turn costs a few hundred tokens, so the
  window can be generous. The chat service (a later PR) reads ``limit`` when it
  calls ``store.load_history``.
- :func:`register_notion_tools` — registers the four read-only Notion selection
  tools (plus the write gate) onto an agent, keeping tool wiring out of the
  orchestrator's construction body.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import Agent

from webtonotion.agents.deps import AgentDeps
from webtonotion.agents.tools.notion import (
    confirm_database,
    find_databases,
    inspect_schema,
    save_to_notion,
)

# Default number of prior exchanges to keep when trimming history.
DEFAULT_HISTORY_EXCHANGES = 20


@dataclass(frozen=True)
class ProcessHistory:
    """History-trim policy: keep the last ``exchanges`` turns.

    One exchange is a user message and the assistant turn (which may include tool
    calls and returns) answering it. ``message_limit`` converts the exchange count
    into the row limit ``store.load_history`` expects.
    """

    exchanges: int = DEFAULT_HISTORY_EXCHANGES

    def __post_init__(self) -> None:
        if self.exchanges < 1:
            raise ValueError("exchanges must be >= 1")

    @property
    def message_limit(self) -> int:
        """Row limit to request from the store for this many exchanges.

        Each exchange spans at least a request row and a response row; tool calls
        add more, so this is a generous over-fetch rather than an exact count. The
        limit can still land mid tool-call/return pair; the store trims the result
        to the next genuine user turn so a truncated history is never malformed
        (see ``SessionStore.load_history``).
        """
        return self.exchanges * 2


def register_notion_tools(agent: Agent[AgentDeps, str]) -> None:
    """Register the Notion selection tools and the write gate onto ``agent``."""
    agent.tool(find_databases)
    agent.tool(inspect_schema)
    agent.tool(confirm_database)
    agent.tool(save_to_notion)
