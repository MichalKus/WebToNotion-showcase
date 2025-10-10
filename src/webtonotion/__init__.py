"""WebToNotion - A FastAPI application for processing URLs and creating Notion pages."""

__version__ = "0.1.0"
__author__ = "MichalKus"
__description__ = "FastAPI application to process URLs and create Notion pages"

# Make exceptions available at package level for easy importing
from .exceptions import *

__all__ = [
    # Version info
    "__version__",
    "__author__", 
    "__description__",
    
    # Core exceptions
    "WebToNotionError",
    
    # Notion exceptions
    "NotionServiceError",
    "NotionAuthenticationError", 
    "NotionRateLimitError",
    "NotionAPIError",
    
    # Web scraping exceptions
    "WebScrapingError",
    "ContentExtractionError",
    "PlaywrightError",
    
    # AI agent exceptions
    "AIAgentError",
    "LLMError",
    "ContentProcessingError",
    
    # Configuration exceptions
    "ConfigurationError",
    
    # API exceptions
    "APIError",
    "ValidationError",
    "ProcessingError",
]