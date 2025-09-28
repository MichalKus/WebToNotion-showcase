### **Services Layer Architecture**

**1. Overview**

The Services layer contains a collection of independent, reusable components that provide specific functionalities to the application. These services are designed to be used as tools by the Core Agent and can also be used by other parts of the application if needed.

**2. Video Scraping Service (`video_scraping_service.py`)**

*   **Purpose**: This service is responsible for fetching and extracting content from web pages, with a special focus on video platforms like YouTube and Instagram.
*   **Key Functions**:
    *   `fetch_content(url: str) -> str`: Given a URL, this function will navigate to the page and return its main content. For social media sites, this will require browser automation.
*   **Implementation Details**:
    *   This service will use a browser automation library like **Playwright** to handle dynamic, JavaScript-heavy websites.
    *   It will need to manage browser instances, handle logins (if necessary), and gracefully deal with anti-scraping measures.
    *   Error handling is critical. The service must be able to handle cases where a page is not found, content is private, or the website structure has changed.

**3. Notion Integration Service (`notion_service.py`)**

*   **Purpose**: This service encapsulates all interactions with the Notion API.
*   **Key Functions**:
    *   `get_databases() -> list[dict]`: Retrieves a list of all databases that the integration has access to.
    *   `create_page(database_id: str, data: dict) -> dict`: Creates a new page in the specified database with the provided data.
*   **Implementation Details**:
    *   This service will use the official `notion-client` library for all API interactions.
    *   It will be initialized with the Notion API key, which will be loaded from the application's configuration.
    *   It will include robust error handling to manage API rate limits and other potential issues.

**4. Monitoring Service (`monitoring_service.py`)**

*   **Purpose**: This service provides an abstraction layer for logging and monitoring. It allows the application to send data to a monitoring tool like Langfuse or Logfire without being tightly coupled to a specific implementation.
*   **Key Functions**:
    *   `log_event(event_name: str, data: dict)`: Logs a specific event (e.g., "agent_decision", "notion_page_created") with associated data.
    *   `log_error(error: Exception)`: Logs an error with its stack trace.
*   **Implementation Details**:
    *   The service will be designed as an interface or a base class, with concrete implementations for each supported monitoring tool (e.g., `LogfireMonitoringService`).
    *   This allows for easy switching between monitoring tools by simply changing the service implementation in the application's configuration.
    *   The chosen monitoring library (`logfire`) will be used to send the data to the corresponding platform.