"""URL processing API endpoints for the WebToNotion application.

This module provides endpoints for processing URLs and creating Notion pages
with comprehensive error handling and validation.
"""

import logging
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from webtonotion.dependencies import get_notion_service, get_video_scraping_service
from webtonotion.exceptions import (
    NotionAPIError,
    NotionAuthenticationError,
    VideoScrapingError,
    WebToNotionError,
)
from webtonotion.models.request import ProcessURLRequest
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
) -> Dict[str, Any]:
    """Process a URL and create a Notion page.

    This endpoint processes various types of URLs (including video URLs)
    and creates corresponding pages in the specified Notion database.

    Args:
        request: URL processing request containing URL, database ID, and custom properties
        notion_service: NotionService instance injected via dependency injection
        video_service: VideoScrapingService instance injected via dependency injection

    Returns:
        Dict[str, Any]: Processing result with page details

    Raises:
        HTTPException: For various error conditions including authentication,
                      validation, and processing errors
    """
    logger.info(f"Processing URL request: {request.url}")

    try:
        # Check if the URL is a video URL
        ##if video_service.is_video_url(request.url):
        logger.info(f"Detected video URL: {request.url}")

        # Process video content
        video_content = await video_service.process_video(request.url)

        logger.info(
            f"Video content fields: title='{video_content.title}', duration='{video_content.duration}', author='{video_content.author}', topics={video_content.topics}"
        )

        # Create Notion page
        # page_response = await notion_service.create_video_page(
        #     database_id=request.database_id,
        #     custom_properties=request.custom_properties,
        #     video_content=video_content,
        # )

        return {
            "success": True,
            "message": "Video URL processed successfully",
            # "page_id": page_response.id,
            # "page_url": page_response.url,
            # "content_type": "video",
            # "video_details": {
            #     "title": video_content.title,
            #     "duration": video_content.duration,
            #     "author": video_content.author,
            #     "topics": video_content.topics,
            # }
        }
    # else:
    #     # For non-video URLs, return a placeholder response
    #     # This would be implemented with web scraping service in the future
    #     logger.info(f"Non-video URL detected: {request.url}")

    #     return {
    #         "success": False,
    #         "message": "Non-video URL processing not yet implemented",
    #         "content_type": "web_page",
    #         "url": request.url
    #     }

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
    except NotionAPIError as e:
        logger.error(f"Notion API error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Notion API error: {str(e)}"
        )
    except WebToNotionError as e:
        logger.error(f"Application error processing URL {request.url}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Processing error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error processing URL {request.url}: {e}")
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
