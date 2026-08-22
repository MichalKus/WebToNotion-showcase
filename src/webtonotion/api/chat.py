"""Chat API endpoints for the agentic orchestrator.

Exposes the multi-turn chat surface: a JSON request/response turn, a history
replay for UIs, and session teardown. The streaming (SSE) route is deferred to a
later PR — it becomes meaningful once the slow video tools exist.

Auth and rate limiting are attached at router inclusion in ``main.py`` (exactly
as for the process router), not per endpoint.
"""

import logging
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from webtonotion.agents.chat_service import ChatService
from webtonotion.agents.session.store import SessionConflictError, SessionNotFoundError
from webtonotion.dependencies import get_chat_service
from webtonotion.exceptions import (
    LLMError,
    NotionAPIError,
    NotionAuthenticationError,
    WebToNotionError,
)
from webtonotion.models.chat import ChatReply, ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "",
    response_model=ChatReply,
    status_code=status.HTTP_200_OK,
    summary="Send a chat message",
    description="Run one orchestrator turn: the agent may inspect databases and, once a "
    "target is confirmed, save to Notion. Returns the assistant's reply.",
)
async def chat(
    request: ChatRequest,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatReply:
    """Handle a single chat turn."""
    try:
        return await chat_service.handle_message(
            conversation_id=request.conversation_id,
            message=request.message,
            session_id=request.session_id,
        )
    except SessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {str(e)}"
        )
    except SessionConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Concurrent message in this session: {str(e)}",
        )
    except NotionAuthenticationError as e:
        logger.error(f"Notion authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Notion API authentication failed: {str(e)}",
        )
    except NotionAPIError as e:
        logger.error(f"Notion API error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Notion API error: {str(e)}",
        )
    except LLMError as e:
        logger.warning(f"Chat turn aborted: {e}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e),
        )
    except WebToNotionError as e:
        logger.error(f"Application error handling chat message: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Processing error: {str(e)}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error handling chat message: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while handling the chat message",
        )


@router.get(
    "/{session_id}",
    response_model=Dict[str, Any],
    summary="Replay a session's history",
    description="Return the full serialized message history of a session for a UI replay.",
)
async def get_session(
    session_id: str,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> Dict[str, Any]:
    """Return the serialized message history for ``session_id``."""
    try:
        messages = await chat_service.get_history(session_id)
    except SessionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Session not found: {str(e)}"
        )
    return {"session_id": session_id, "messages": messages}


@router.delete(
    "/{session_id}",
    response_model=Dict[str, Any],
    summary="End a session",
    description="Delete a session and drop its message history. Idempotent.",
)
async def delete_session(
    session_id: str,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> Dict[str, Any]:
    """Delete a session and its history."""
    await chat_service.end_session(session_id)
    return {"deleted": True, "session_id": session_id}
