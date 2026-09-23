"""URL processing API endpoints for the WebToNotion application.

This module provides endpoints for processing URLs and creating Notion pages
with comprehensive error handling and validation.
"""

import logging
from typing import Annotated, Any, Dict

import logfire
from fastapi import APIRouter, Depends, HTTPException, status

from webtonotion.agents.writer import build_page_content, write_video_page
from webtonotion.config.settings import Settings
from webtonotion.dependencies import get_notion_service, get_settings, get_video_scraping_service
from webtonotion.exceptions import (
    NotionAPIError,
    NotionAuthenticationError,
    NotionRateLimitError,
    VideoScrapingError,
    WebToNotionError,
)
from webtonotion.models.chat import SaveResult
from webtonotion.models.request import ProcessURLRequest
from webtonotion.models.video import VideoPageContent
from webtonotion.services.notion_service import NotionService
from webtonotion.services.video_scraping_service import VideoScrapingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/process", tags=["processing"])


@router.post(
    "/url",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Process URL and create Notion page",
    description="Process a given URL, extract content, and create a structured page in Notion",
)
async def process_url(
    request: ProcessURLRequest,
    notion_service: Annotated[NotionService, Depends(get_notion_service)],
    video_service: Annotated[VideoScrapingService, Depends(get_video_scraping_service)],
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> Dict[str, Any]:
    """Process a URL and create a Notion page.

    This endpoint processes various types of URLs (including video URLs)
    and creates corresponding pages in the specified Notion database. It
    shares the single write path (:mod:`webtonotion.agents.writer`) with
    the agentic ``save_to_notion`` tool.

    Args:
        request: URL processing request containing URL, database ID, and custom properties
        notion_service: NotionService instance injected via dependency injection
        video_service: VideoScrapingService instance injected via dependency injection
        app_settings: Application settings injected via dependency injection

    Returns:
        Dict[str, Any]: Processing result with page details

    Raises:
        HTTPException: For various error conditions including authentication,
                      validation, and processing errors
    """
    logger.info(f"Processing URL request: {request.url}")

    try:
        with logfire.span("Request validation"):
            # Validate request and get database schema
            db_schema = await _validate_request_and_get_db_schema(
                request=request,
                notion_service=notion_service,
                video_service=video_service,
            )
            # _validate_request_and_get_db_schema already 400s when database_id is
            # missing; this assert only narrows the type for mypy.
            assert request.database_id is not None

        with logfire.span("Video content assembly"):
            content = await build_page_content(video_service=video_service, url=str(request.url))
            logger.info(
                f"Video content assembled successfully: title='{content.title}', "
                f"duration='{content.duration}', author='{content.author}', "
                f"platform='{content.platform}', language='{content.language}'"
            )

        with logfire.span("Notion page creation"):
            result = await write_video_page(
                notion_service=notion_service,
                settings=app_settings,
                database_id=request.database_id,
                content=content,
                db_schema=db_schema,
            )

        logger.info("Request processed successfully")
        # Return comprehensive success response
        return _build_success_response(page_response=result, content=content)

    except VideoScrapingError as e:
        logger.error(f"Video scraping error for URL {request.url}: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to process video URL: {str(e)}",
        )
    except NotionAuthenticationError as e:
        logger.error(f"Notion authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Notion API authentication failed: {str(e)}",
        )
    except (NotionAPIError, NotionRateLimitError) as e:
        logger.error(f"Notion API error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Notion API error: {str(e)}"
        )
    except WebToNotionError as e:
        logger.error(f"Application error processing URL {request.url}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Processing error: {str(e)}"
        )
    except HTTPException:
        # Re-raise HTTP exceptions without modification
        raise
    except Exception as e:
        logger.error(f"Unexpected error processing URL {request.url}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing the URL",
        )


@router.get(
    "/status",
    response_model=Dict[str, Any],
    summary="Get processing service status",
    description="Check the status and health of the URL processing service",
)
async def get_processing_status() -> Dict[str, Any]:
    """Get the current status of processing capabilities.

    Returns:
        Dict[str, Any]: Status of various processing features
    """
    return {
        "video_scraping": "available",
        "web_scraping": "not_implemented",
        "notion_integration": "available",
        "ai_agents": "available",
        "supported_video_platforms": [
            "youtube.com",
            "youtu.be",
            "vimeo.com",
            "dailymotion.com",
            "twitch.tv",
        ],
    }


def _build_success_response(
    page_response: SaveResult,
    content: VideoPageContent,
) -> Dict[str, Any]:
    """Build the success response for URL processing.

    Args:
        page_response: The shared write path result for the created page
        content: The bounded DTO that was mapped onto the database

    Returns:
        Dict[str, Any]: Complete success response with all details
    """
    return {
        "success": True,
        "message": "Video URL processed and Notion page created successfully",
        "page_id": page_response.page_id,
        "page_url": page_response.page_url,
        "content_type": "video",
        "video_details": {
            "title": content.title,
            "author": content.author,
            "duration": content.duration,
            "platform": content.platform,
            "language": content.language,
            "transcript_length": len(content.transcript_excerpt),
            "summary_length": len(content.summary),
        },
        "processing_stats": {
            "transcription_available": bool(content.transcript_excerpt),
            "summary_available": bool(content.summary),
        },
    }


async def _validate_request_and_get_db_schema(
    request: ProcessURLRequest,
    notion_service: NotionService,
    video_service: VideoScrapingService,
) -> Dict[str, Any]:
    """Validate the request and fetch the Notion database schema.

    This helper function performs initial validation of the processing request:
    - Validates that a database ID is provided
    - Fetches the Notion database schema to verify access
    - Confirms the URL is a supported video URL

    Args:
        request: The URL processing request containing URL and database ID
        notion_service: Service for Notion API interactions
        video_service: Service for video URL validation

    Returns:
        Dict[str, Any]: The Notion database schema

    Raises:
        HTTPException: If database ID is missing (400) or URL is not a video (400)
    """
    if not request.database_id:
        logger.error("Database ID is required for creating Notion pages")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database ID is required to create a Notion page",
        )

    logger.info("Validating notion access")
    db_schema = await notion_service.get_database_properties(request.database_id)

    logger.info(f"Checking if URL is a video URL: {request.url}")
    is_video = await video_service.is_video_url(request.url)

    if not is_video:
        logger.error(f"Non-video URL detected: {request.url}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only video URLs are supported for processing",
        )

    return db_schema
