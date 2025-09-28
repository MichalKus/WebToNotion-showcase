### **API Layer Architecture**

**1. Overview**

The API layer is the entry point for all external interactions with the WebToNotion application. It's built using FastAPI and is responsible for receiving requests, validating them, and passing them to the core application logic for processing.

**2. API Endpoints**

*   **`POST /api/v1/process-url`**
    *   **Description**: This is the primary endpoint for the application. It accepts a URL, which is then processed by the Core Agent Service.
    *   **Request Body**:
        ```json
        {
            "url": "string"
        }
        ```
    *   **Success Response (200 OK)**:
        ```json
        {
            "status": "success",
            "message": "Successfully processed and added to Notion.",
            "notion_page_url": "string"
        }
        ```
    *   **Error Responses**:
        *   **400 Bad Request**: Invalid URL or malformed request body.
            ```json
            {
                "status": "error",
                "message": "Invalid URL provided."
            }
            ```
        *   **422 Unprocessable Entity**: The URL is valid, but the content cannot be processed (e.g., unsupported website, private video).
            ```json
            {
                "status": "error",
                "message": "Could not process content from the provided URL."
            }
            ```
        *   **500 Internal Server Error**: An unexpected error occurred in the application.
            ```json
            {
                "status": "error",
                "message": "An internal server error occurred."
            }
            ```

**3. Security and Authentication**

Initially, the API will be open for simplicity. However, in a production environment, it should be secured. The recommended approach is to use an API key passed in the `Authorization` header.

*   **Header**: `Authorization: Bearer <YOUR_API_KEY>`

This can be implemented in FastAPI using a `Depends` function that checks for a valid API key.

**4. Implementation Details**

*   The endpoint will be defined in `src/api/process.py`.
*   It will use a Pydantic model from `src/models/request.py` to validate the incoming request body.
*   The endpoint will be asynchronous (`async def`) to handle concurrent requests efficiently.
*   It will call the `CoreAgentService.process_url()` method to initiate the processing.