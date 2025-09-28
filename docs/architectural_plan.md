### **Architectural Plan: WebToNotion**

**1. Feature Summary & Core Goal**
The main goal of this project is to create an AI-powered agent that can process URLs from social media platforms like YouTube, Facebook and Instagram, with a primary focus on short videos. The agent will extract structured information (e.g., location, author, content) from the provided link and, based on its understanding of a user's Notion workspace, intelligently decide which Notion database is the most appropriate destination for this information. The project will leverage Python with the `pydantic-ai` library for the core agent logic and will integrate with monitoring tools like Langfuse or Logfire to ensure observability.

**2. Architectural Impact & Integration Strategy**
This project will be built as a new, standalone Python application following a modular, service-oriented architecture. It will not directly modify any existing systems but will interact with two external services: the source web pages (via HTTP requests) and the Notion API. The core of the application will be a FastAPI server that exposes an endpoint to receive URLs for processing. The processing itself will be handled by an asynchronous agent built with `pydantic-ai`.

The key architectural components will be:
- A **Web API** layer to handle incoming requests.
- A **Core Agent Service** responsible for the main processing logic.
- A **Web Scraping Service** to fetch content from URLs.
- A **Notion Integration Service** to interact with the Notion API.
- A **Monitoring Service** to send data to Langfuse/Logfire.

**3. Proposed Solution Architecture**

*   **High-Level Design:**
    *   [View High-Level Architecture Diagram](diagrams/high_level_architecture.md)
    *   [View Component Diagram](diagrams/component_diagram.md)
    *   [View Sequence Diagram](diagrams/sequence_diagram.md)

*   **Detailed Architecture:**
    *   [API Layer Architecture](architecture/api_architecture.md)
    *   [Core Agent Architecture](architecture/core_agent_architecture.md)
    *   [Services Layer Architecture](architecture/services_architecture.md)
    *   [Data Models Architecture](architecture/models_architecture.md)
    *   [Configuration Architecture](architecture/config_architecture.md)

*   **Component Breakdown:**
    *   **`main.py`**: The entry point of the application. It will initialize the FastAPI app, set up logging, and include the API routers.
    *   **`api/`**: This module will contain the FastAPI routers.
        *   `process.py`: Defines the `/api/v1/process-url` endpoint.
    *   **`core/`**: The central logic of the application.
        *   `agent.py`: Contains the `PydanticAIAgent` responsible for orchestrating the entire process, from scraping to Notion entry creation. It will use tools to interact with other services.
    *   **`services/`**: A collection of services that perform specific tasks.
        *   `video_scraping_service.py`: A specialized tool for the agent to handle content extraction from video platforms like YouTube and Instagram. This will likely require browser automation (e.g., Playwright) to handle dynamic content and authentication.
        *   `notion_service.py`: A tool for the agent. It will handle all interactions with the Notion API, such as listing databases and creating pages. It will use the official `notion-client` library.
        *   `monitoring_service.py`: A service to abstract the interaction with the chosen monitoring tool (Langfuse or Logfire), allowing for easy switching if needed.
    *   **`models/`**: Pydantic models for data validation and structuring.
        *   `request.py`: Defines the model for the incoming URL processing request.
        *   `notion.py`: Defines models for Notion databases and pages.
    *   **`config/`**: Configuration management.
        *   `settings.py`: Pydantic-based settings management to load configuration from environment variables (e.g., Notion API key, monitoring service credentials).

*   **Data Model Changes:**
    *   This is a new application, so there are no changes to existing data models. The primary models will be Pydantic models representing the request payload and the data structures for Notion pages and databases.

*   **API Endpoints:**
    *   **`POST /api/v1/process-url`**:
        *   **Request Body**: `{ "url": "https://example.com/some-article" }`
        *   **Success Response (200 OK)**: `{ "status": "success", "message": "Successfully processed and added to Notion.", "notion_page_url": "https://www.notion.so/..." }`
        *   **Error Response (4xx/5xx)**: `{ "status": "error", "message": "Detailed error message." }`

*   **Non-Functional Considerations:**
    *   **Security**: API keys and other secrets will be managed via environment variables and a `Pydantic` settings object. The API will include input validation to prevent common vulnerabilities.
    *   **Scalability**: The application will be designed to run in a containerized environment (Docker) and can be scaled horizontally. The use of asynchronous operations in FastAPI and the services will ensure efficient handling of concurrent requests.
    *   **Observability**: Integration with Langfuse or Logfire will be a core feature. The agent's decisions, tool usage, and any errors will be logged to provide a clear trace of each processing request.

**4. Detailed Task Breakdown**

*   **Project Setup:**
    *   `[ ] Task: Initialize Python project with pyproject.toml using pip.`
    *   `[ ] Task: Set up the directory structure (src, tests, docs, config).`
    *   `[x] Task: Set up a virtual environment (venv).`
    *   `[x] Task: Install initial dependencies: fastapi, uvicorn, pydantic, pydantic-ai, httpx, beautifulsoup4, notion-client, python-dotenv.`
    *   `[x] Task: Choose and install a monitoring library (logfire or langfuse).`

*   **Backend:**
    *   `[ ] Task: Implement the FastAPI application entry point in main.py.`
    *   `[ ] Task: Create the Pydantic model for the URL processing request.`
    *   `[ ] Task: Implement the /api/v1/process-url endpoint in api/process.py.`
    *   `[ ] Task: Implement the settings management in config/settings.py to load secrets.`
    *   `[ ] Task: Implement the Web Scraping Service (services/scraping_service.py) with a function to get content from a URL.`
    *   `[ ] Task: Implement the Notion Integration Service (services/notion_service.py) with functions to list databases and create pages.`
    *   `[ ] Task: Implement the Monitoring Service (services/monitoring_service.py) to log events.`
    *   `[ ] Task: Implement the Core Agent Service (core/agent.py) using pydantic-ai, integrating the scraping and Notion services as tools.`

*   **Database:**
    *   `[ ] Task: No database setup is required for this application itself, as it only interacts with the Notion API.`

*   **QA / Testing:**
    *   `[ ] Task: Write unit tests for the Web Scraping Service.`
    *   `[ ] Task: Write unit tests for the Notion Integration Service (using mocks for the Notion API).`
    *   `[ ] Task: Write integration tests for the /api/v1/process-url endpoint.`
    *   `[ ] Task: Manually test the end-to-end flow with various URLs.`

*   **Documentation:**
    *   `[ ] Task: Create a README.md with setup and usage instructions.`
    *   `[ ] Task: Add OpenAPI documentation for the API endpoint using FastAPI's automatic docs generation.`

**5. Risks & Open Questions for the Team**

*   **Risks:**
    *   `[RISK-1]: Web scraping is fragile.` The structure of target websites can change at any time, breaking the scraping logic. The agent needs robust error handling to manage cases where content extraction fails.
    *   `[RISK-2]: Scraping social media is challenging.` Websites like Facebook and Instagram are notoriously difficult to scrape. They use dynamic content loading, require authentication, and have strong anti-bot measures. A simple HTTP-based approach will likely fail, and a more robust solution using browser automation (e.g., Playwright) will be necessary. This adds complexity to the project.
    *   `[RISK-3]: Rate limiting.` Both the websites being scraped and the Notion API will have rate limits. The application must handle these gracefully, potentially with backoff-and-retry mechanisms.
    *   `[RISK-4]: AI "hallucination".` The AI agent might incorrectly interpret the content or make a poor decision about which Notion database to use. The prompts and logic must be carefully designed to be as accurate as possible, and logging is crucial for debugging these cases.

*   **Open Questions:**
    *   `[Q-1]: Which monitoring tool (Langfuse or Logfire) should be prioritized for the initial implementation, and why?
    *   [A-1]: Logfire has been chosen for the initial implementation due to its good integration with Pydantic and FastAPI.`
    *   `[Q-2]: What is the expected format of the Notion databases? Will they have a consistent structure (e.g., specific column names like "URL", "Source", "Content") that the agent can rely on?`
    *   `[Q-3]: Are there any specific types of websites or content (e.g., social media, news articles, e-commerce products) that should be prioritized for support?`
    *   `[A-3]: The initial implementation will prioritize support for short videos from Facebook and Instagram, particularly those related to attractions and hotels.`