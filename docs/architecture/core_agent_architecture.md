### **Core Agent Architecture**

**1. Overview**

The Core Agent is the heart of the WebToNotion application. It is an AI-powered component responsible for orchestrating the entire process of fetching web content, understanding it, and then creating a structured entry in a relevant Notion database. It will be built using the `pydantic-ai` library, which allows for the creation of structured, predictable AI agents.

**2. Core Responsibilities**

*   **Orchestration**: The agent manages the flow of data between the different services (scraping, Notion, monitoring).
*   **Decision Making**: It uses an LLM to analyze the scraped content and decide which Notion database is the most appropriate destination.
*   **Data Extraction**: It extracts relevant information from the content (e.g., title, author, location, summary) and maps it to the fields of the chosen Notion database.
*   **Tool Usage**: The agent will be equipped with a set of tools (services) that it can call to perform specific actions, such as fetching content from a URL or creating a page in Notion.

**3. **Agent Logic Flow**

The agent will follow these steps when processing a URL:

1.  **Receive URL**: The agent is invoked with a URL from the API layer.
2.  **Invoke Video Scraping Service**: It calls the `VideoScrapingService` to get the structured `VideoContent` from the web page.
3.  **Find Candidate Databases**: The agent uses the `DatabaseSelectionService` to find a small set of the most relevant Notion databases. (See [Database Selection Architecture](database_selection_architecture.md) for details).
4.  **Select Best Database**: The agent sends the `VideoContent` and the candidate databases to the LLM with a focused prompt that instructs it to analyze the video content and choose the single most appropriate database from the candidates.
5.  **Map Data to Database Fields**: Once the database is selected, the agent makes a second LLM call with the `VideoContent` and the specific properties/schema of the chosen database. This prompt focuses solely on extracting and mapping the relevant data from the video content to match the database's field structure.
6.  **Create Notion Page**: The agent calls the `NotionService` with the chosen database ID and the mapped data to create a new page in Notion.
7.  **Log and Monitor**: Throughout the process, the agent logs key events and decisions to the `MonitoringService`.
8.  **Return Result**: The agent returns the result of the operation (e.g., the URL of the newly created Notion page) to the API layer.

**4. Implementation Details**

The agent will be implemented as a `PydanticAIAgent` from the `pydantic-ai` library. It will be initialized with the `VideoScrapingService` and `NotionIntegrationService`. The public methods of these services will be exposed as tools for the agent.

**5. Structured Output**

The agent will leverage `pydantic-ai`'s structured output capabilities. The LLM's responses will be parsed into Pydantic models, ensuring that the data passed between services is always validated and in the correct format.

**6. Error Handling**

The agent will implement robust error handling for all its operations. This includes:

*   **Web Scraping Failures**: Retry mechanisms and graceful failure if content cannot be retrieved.
*   **Notion API Errors**: Handling of API rate limits, permission issues, and other potential errors.
*   **LLM Failures**: Fallback mechanisms or error logging if the LLM fails to generate a valid response.