### **Services Layer Architecture**

**1. Overview**

The Services layer contains a collection of independent, reusable components that provide specific functionalities to the application. These services are designed to be used as tools by the Core Agent and can also be used by other parts of the application if needed.

**2. Video Scraping Service (`video_scraping_service.py`)**

*   **Purpose**: This service is responsible for extracting comprehensive content from video URLs from platforms like YouTube, Instagram, and Facebook.
*   **Key Functions**:
    *   `process_video(url: str) -> VideoContent`: Given a video URL, this function orchestrates the entire process of downloading, transcribing, and analyzing the video content.
*   **Implementation Details**:
    *   **Primary Method (`yt-dlp`)**: The service's main strategy is to use the `yt-dlp` library to download the video's audio stream and extract all available metadata (title, description, author, etc.).
    *   **Audio Transcription**: The downloaded audio is then sent to an external transcription service (e.g., OpenAI Whisper) to get a full text transcript.
    *   **Content Consolidation**: The video's description (from metadata) and the audio transcript are combined into a single text document for comprehensive analysis.
    *   **AI Analysis**: This consolidated text is passed to a `pydantic-ai` agent, which extracts structured information (e.g., topics, locations, sentiment) based on a predefined schema.
    *   **Fallback Mechanism (Playwright)**: If `yt-dlp` fails (e.g., for private content requiring a login), the service will fall back to using **Playwright**. In this mode, it will launch a browser, potentially log in to the platform, and scrape the necessary metadata from the page as a last resort.
    *   **Error Handling**: The service includes robust error handling to manage failures in `yt-dlp`, the transcription service, or the fallback scraping process.

**3. Notion Integration Service (`notion_service.py`)**

*   **Purpose**: This service encapsulates all interactions with the Notion API.
*   **Key Functions**:
    *   `get_databases() -> list[dict]`: Retrieves a list of all databases that the integration has access to.
    *   `create_page(database_id: str, data: dict) -> dict`: Creates a new page in the specified database with the provided data.
    *   `create_video_page(database_id: str, video_content: VideoContent) -> NotionPageResponse`: Orchestrates the creation of a video page by fetching the database schema and using an AI agent to map the content.
    *   `get_database_properties(database_id: str) -> dict`: Retrieves the exact schema of a Notion database.
*   **Implementation Details**:
    *   **Hybrid Integration**: Combines deterministic API calls (to get schema) with AI-driven mapping (to fill schema).
    *   **Notion Mapper Agent**: Uses a `pydantic-ai` agent (`src/webtonotion/services/analysis/notion_mapper.py`) to intelligently map video metadata (title, transcript, sentiment) to the user's specific database properties, handling naming variations (e.g., "URL" vs "Link").
    *   **Official Client**: Uses `notion-client` for all API interactions.
    *   **Resilience**: Includes rate limiting and robust error handling.

**4. Monitoring Service (`monitoring_service.py`)**

*   **Purpose**: This service provides an abstraction layer for logging and monitoring. It allows the application to send data to a monitoring tool like Logfire without being tightly coupled to a specific implementation.
*   **Key Functions**:
    *   `log_event(event_name: str, data: dict)`: Logs a specific event (e.g., "agent_decision", "notion_page_created") with associated data.
    *   `log_error(error: Exception)`: Logs an error with its stack trace.
*   **Implementation Details**:
    *   The service will be designed as an interface or a base class, with concrete implementations for each supported monitoring tool (e.g., `LogfireMonitoringService`).
    *   This allows for easy switching between monitoring tools by simply changing the service implementation in the application's configuration.
    *   The chosen monitoring library (`logfire`) will be used to send the data to the corresponding platform.