### **Configuration Architecture**

**1. Overview**

The configuration of the WebToNotion application is managed using a combination of environment variables and a Pydantic settings model. This approach provides a robust and flexible way to configure the application for different environments (development, testing, production) without modifying the code.

**2. Settings Management**

*   **`pydantic-settings`**: This library is used to create a `Settings` model that loads configuration from environment variables and `.env` files.
*   **`.env` file**: A `.env` file will be used to store environment variables for local development. This file should be added to `.gitignore` to prevent secrets from being committed to version control.

**3. Configuration File (`config/settings.py`)**

This file will contain the `Settings` model, which defines all the configuration variables for the application.

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Notion API Key
    notion_api_key: str

    # Monitoring Service (Logfire)
    logfire_token: str

    # Optional: API Key for securing the API
    api_key: str | None = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# Global instance of the settings
settings = Settings()
```

**4. Usage**

To access the configuration in the application, you can simply import the `settings` object from `config.settings`:

```python
from config.settings import settings

# Example usage
notion_api_key = settings.notion_api_key
```

This approach ensures that the configuration is loaded only once and is available throughout the application in a consistent and type-safe manner.