"""Custom exceptions for the WebToNotion application.

This module contains all custom exception classes used throughout the application,
providing a centralized location for error handling and maintaining clean architecture.
"""


class WebToNotionError(Exception):
    """Base exception for all WebToNotion application errors.

    This serves as the root exception class for all custom exceptions
    in the application, allowing for easy exception hierarchy management.
    """

    pass


# Notion Service Exceptions
class NotionServiceError(WebToNotionError):
    """Base exception for Notion service errors.

    This is the parent class for all Notion-related service exceptions,
    providing a common interface for handling Notion API issues.
    """

    pass


class NotionAuthenticationError(NotionServiceError):
    """Raised when Notion API authentication fails.

    This exception is raised when:
    - Invalid or missing API key
    - Expired authentication tokens
    - Insufficient permissions for the requested operation
    """

    pass


class NotionRateLimitError(NotionServiceError):
    """Raised when Notion API rate limit is exceeded.

    This exception is raised when the application exceeds the Notion API
    rate limits and should trigger retry mechanisms with backoff.
    """

    pass


class NotionAPIError(NotionServiceError):
    """Raised when Notion API returns an error.

    This is a general exception for Notion API errors that don't fall
    into more specific categories like authentication or rate limiting.

    Attributes:
        message: Error message
        status_code: HTTP status code if available
    """

    def __init__(self, message="Unexpected Notion API error", status_code=None):
        self.status_code = status_code
        super().__init__(message)


# Web Scraping Exceptions
class WebScrapingError(WebToNotionError):
    """Base exception for web scraping errors.

    This is the parent class for all web scraping related exceptions.
    """

    pass


class ContentExtractionError(WebScrapingError):
    """Raised when content extraction from a URL fails.

    This exception is raised when:
    - URL is inaccessible
    - Content cannot be parsed
    - Required content elements are missing
    """

    pass


class PlaywrightError(WebScrapingError):
    """Raised when Playwright browser automation fails.

    This exception is raised when browser automation encounters
    issues during content extraction or page interaction.
    """

    pass


# Video Scraping Exceptions
class VideoScrapingError(WebScrapingError):
    """Base exception for video scraping errors.

    This is the parent class for all video scraping related exceptions.
    """

    pass


class VideoDownloadError(VideoScrapingError):
    """Raised when video download fails.

    This exception is raised when:
    - Video URL is inaccessible
    - Video format is not supported
    - Download process encounters errors
    """

    pass


class TranscriptionError(VideoScrapingError):
    """Raised when audio transcription fails.

    This exception is raised when:
    - Audio extraction from video fails
    - OpenAI Whisper API is unavailable
    - Audio format is not supported for transcription
    """

    pass


class PlaywrightFallbackError(VideoScrapingError):
    """Raised when Playwright fallback fails.

    This exception is raised when Playwright cannot extract
    video metadata as a fallback mechanism.
    """

    pass


# AI Agent Exceptions
class AIAgentError(WebToNotionError):
    """Base exception for AI agent errors.

    This is the parent class for all AI agent related exceptions.
    """

    pass


class LLMError(AIAgentError):
    """Raised when LLM processing fails.

    This exception is raised when:
    - LLM API is unavailable
    - Invalid or malformed responses from LLM
    - Token limits exceeded
    """

    pass


class ContentProcessingError(AIAgentError):
    """Raised when content processing by AI agents fails.

    This exception is raised when AI agents cannot properly
    process or structure the extracted content.
    """

    pass


# Configuration Exceptions
class ConfigurationError(WebToNotionError):
    """Raised when application configuration is invalid.

    This exception is raised when:
    - Required environment variables are missing
    - Configuration values are invalid
    - Settings validation fails
    """

    pass


# API Exceptions
class APIError(WebToNotionError):
    """Base exception for API-related errors.

    This is the parent class for all API endpoint related exceptions.
    """

    pass


class ValidationError(APIError):
    """Raised when request validation fails.

    This exception is raised when incoming API requests
    fail validation checks or contain invalid data.
    """

    pass


class ProcessingError(APIError):
    """Raised when URL processing fails.

    This exception is raised when the main URL processing
    workflow encounters unrecoverable errors.
    """

    pass
