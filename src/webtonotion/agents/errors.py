"""Shared error classification for the orchestrator's tools and write path.

A single source of truth for the two exception/status groupings tools need to make
recoverable-vs-fatal decisions, so ``agents/tools/notion.py`` and ``agents/writer.py``
cannot silently drift from ``agents/tools/video.py``'s definitions.
"""

from __future__ import annotations

from webtonotion.exceptions import ContentProcessingError, VideoScrapingError

RECOVERABLE_VIDEO_ERRORS = (VideoScrapingError, ContentProcessingError)
"""Failures the agent should see and work around, rather than aborting the run."""

FATAL_AUTH_HTTP_STATUS = frozenset({401, 403})
"""HTTP statuses that mean a bad API key/config, not a transient failure -- callers
re-raise rather than recover."""
