### **Data Models Architecture**

**1. Overview**

The Data Models are a crucial part of the application, ensuring that data is structured, validated, and consistent across different components. Pydantic is used for defining these models, which provides data validation and serialization out of the box.

**2. Request Models (`models/request.py`)**

*   **`ProcessURLRequest`**: This model is used to validate the incoming request to the `/api/v1/process-url` endpoint.

    ```python
    from pydantic import BaseModel, HttpUrl

    class ProcessURLRequest(BaseModel):
        url: HttpUrl
    ```

**3. Notion Models (`models/notion.py`)**

These models represent the structure of data that is sent to and received from the Notion API. They will be used by the `NotionService` and the `CoreAgent`.

*   **`NotionDatabase`**: Represents a Notion database.

    ```python
    from pydantic import BaseModel

    class NotionDatabase(BaseModel):
        id: str
        name: str
        properties: dict
    ```

*   **`NotionPage`**: Represents a page to be created in Notion. The structure of this model will be dynamic, as it depends on the properties of the target database. The `CoreAgent` will be responsible for constructing the data for this model based on the LLM's output.

**4. Configuration Models (`config/settings.py`)**

*   **`Settings`**: This model is used to load and validate the application's configuration from environment variables. It ensures that all required settings are present and have the correct types.

    ```python
    from pydantic_settings import BaseSettings

    class Settings(BaseSettings):
        notion_api_key: str
        logfire_token: str

        class Config:
            env_file = ".env"
    ```