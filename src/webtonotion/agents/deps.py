"""Runtime dependencies for the orchestrator agent.

``AgentDeps`` is the per-run context handed to every tool through
``RunContext[AgentDeps]``. It mirrors the ``MapperDependencies`` pattern in
``services/analysis/notion_mapper.py``: services and state are injected once when
the run starts rather than constructed inside a tool. The dataclass is frozen so a
tool cannot mutate the wiring mid-run; the confirm-gate lives on the mutable
``Session`` record it points at, not on the frozen container.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from webtonotion.agents.session.store import Session, SessionStore

if TYPE_CHECKING:  # heavy / optional imports kept out of runtime import graph
    from webtonotion.config.settings import Settings
    from webtonotion.services.notion_service import NotionService
    from webtonotion.services.storage.file_cache import FileCacheService
    from webtonotion.services.video_scraping_service import VideoScrapingService


@dataclass(frozen=True)
class AgentDeps:
    """Dependencies injected into an orchestrator run.

    Attributes:
        notion_service: Pure Notion API client the read-only tools call.
        session: The current session record; its ``confirmed_database_id`` is the
            write gate the ``save_to_notion`` tool checks.
        store: Session store used to persist a confirmed database id.
        settings: Application settings (model, retries, limits).
        video_service: Pipeline stages the video tools call (metadata, transcript,
            analysis), each independently cached.
        cache: Per-artifact cache. The ``metadata`` artifact holds the video's
            transcript and its cached summaries alongside title/author, so a repeated
            request -- for a transcript ref, a summary, or an answer -- costs nothing.
    """

    notion_service: "NotionService"
    session: Session
    store: SessionStore
    settings: "Settings"
    video_service: "VideoScrapingService"
    cache: "FileCacheService"
