# WebToNotion API Documentation

This document provides comprehensive documentation for the WebToNotion API endpoints, focusing on video processing capabilities.

## Base URL

```
http://localhost:8000
```

## Authentication

Currently, the API does not require authentication for processing endpoints. However, you must configure valid API keys in your environment:

- `NOTION_API_KEY`: Required for creating Notion pages
- `OPENAI_API_KEY`: Required for video transcription and AI analysis

## Endpoints

### 1. Process URL

Process any supported URL and create a corresponding Notion page.

**Endpoint**: `POST /process/url`

**Content-Type**: `application/json`

#### Request Body

```json
{
  "url": "string",                    // Required: URL to process
  "database_id": "string"             // Required: Notion database ID
}
```

#### Request Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | The URL to process. Must be a valid HTTP/HTTPS URL |
| `database_id` | string | Yes | The Notion database ID where the page will be created |

#### Response

The response format depends on the type of content processed:

##### Video Content Response

```json
{
  "success": true,
  "message": "Video URL processed and Notion page created successfully",
  "page_id": "string",
  "page_url": "string",
  "content_type": "video",
  "video_details": {
    "title": "string",
    "duration": 300,
    "author": "string",
    "topics": ["topic1", "topic2"],
    "sentiment": "positive|negative|neutral",
    "locations": ["location1", "location2"],
    "transcript_length": 1500,
    "metadata": {
      "key_insights": "string (json)",
      "content_category": "string"
    }
  },
  "processing_stats": {
    "transcription_available": true,
    "ai_analysis_completed": true,
    "cache_hit": false
  }
}
```

##### Non-Video Content Response

```json
{
  "success": false,
  "message": "Non-video URL processing not yet implemented",
  "content_type": "web_page",
  "url": "string"
}
```

#### Video Content Fields

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Video title |
| `description` | string | Video description |
| `author` | string | Video creator/channel name |
| `duration` | integer | Video duration in seconds |
| `published_at` | string | Publication date in ISO format |
| `topics` | array | AI-extracted topics from the video |
| `sentiment` | string | Overall sentiment analysis result |
| `locations` | array | Locations mentioned in the video |
| `transcript_preview` | string | First 200 characters of the transcript |
| `metadata` | object | Additional video metadata |

#### Error Responses

##### Validation Error (422)

```json
{
  "detail": [
    {
      "loc": ["body", "field_name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

##### Video Scraping Error (422)

```json
{
  "detail": "Failed to process video URL: [error details]"
}
```

##### Notion Authentication Error (401)

```json
{
  "detail": "Notion API authentication failed: [error details]"
}
```

##### Notion API Error (503)

```json
{
  "detail": "Notion API error: [error details]"
}
```

##### Generic Error (500)

```json
{
  "detail": "An unexpected error occurred: [error details]"
}
```

### 2. Processing Status

Get the current status of processing capabilities and supported platforms.

**Endpoint**: `GET /process/status`

#### Response

```json
{
  "video_scraping": "available|not_implemented",
  "web_scraping": "available|not_implemented",
  "notion_integration": "available|not_implemented",
  "ai_agents": "available|not_implemented",
  "supported_video_platforms": [
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "dailymotion.com",
    "twitch.tv",
    "facebook.com",
    "instagram.com"
  ]
}
```

#### Status Fields

| Field | Description |
|-------|-------------|
| `video_scraping` | Status of video content processing |
| `web_scraping` | Status of general web content processing |
| `notion_integration` | Status of Notion API integration |
| `ai_agents` | Status of AI-powered content analysis |
| `supported_video_platforms` | List of supported video platforms |

### 3. Health Check

Check the health status of the application.

**Endpoint**: `GET /health`

#### Response

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "service": "WebToNotion"
}
```

## Supported Video Platforms

The video processing service supports the following platforms:

- **YouTube** (`youtube.com`, `youtu.be`)
- **Vimeo** (`vimeo.com`)
- **Dailymotion** (`dailymotion.com`)
- **Twitch** (`twitch.tv`)
- **Facebook** (`facebook.com`)
- **Instagram** (`instagram.com`)

## Video Processing Pipeline

When a video URL is processed, the following steps occur:

1. **URL Validation**: Verify the URL format and platform support
2. **Content Extraction**: Use yt-dlp to extract video metadata
3. **Audio Transcription**: Download audio and transcribe using OpenAI Whisper
4. **AI Analysis**: Analyze content for topics, sentiment, and locations using PydanticAI
5. **Caching**: Store processed content for future requests
6. **Notion Integration**: Create a structured page in the specified database
7. **Response**: Return detailed processing results

## Rate Limiting

Currently, there are no explicit rate limits on the API endpoints. However, be mindful of:

- **OpenAI API limits**: Transcription requests are subject to OpenAI's rate limits
- **Notion API limits**: Page creation is subject to Notion's rate limits
- **Video platform limits**: Some platforms may have their own rate limiting

## Error Handling

The API implements comprehensive error handling:

- **Validation errors**: Invalid request data returns 422 status
- **Authentication errors**: Invalid API keys return 401 status
- **Service errors**: External service failures return 503 status
- **Unexpected errors**: Internal errors return 500 status

All errors include detailed messages to help with debugging.

## Examples

### Process a YouTube Video

```bash
curl -X POST "http://localhost:8000/process/url" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "database_id": "your_notion_database_id",
    "custom_properties": {
      "source": "youtube",
      "priority": "high"
    }
  }'
```

### Check Processing Status

```bash
curl -X GET "http://localhost:8000/process/status"
```

### Health Check

```bash
curl -X GET "http://localhost:8000/health"
```

## Development and Testing

For development and testing purposes, you can use the following test markers:

- `@pytest.mark.integration`: Integration tests requiring external services
- `@pytest.mark.slow`: Tests that take longer to execute
- `@pytest.mark.requires_api_keys`: Tests requiring valid API keys
- `@pytest.mark.requires_internet`: Tests requiring internet connectivity

## Troubleshooting

### Common Issues

1. **"Notion API authentication failed"**
   - Verify your `NOTION_API_KEY` is correct
   - Ensure the integration has access to the target database

2. **"Failed to process video URL"**
   - Check if the video platform is supported
   - Verify the URL is accessible and not private
   - Ensure FFmpeg is installed for audio processing

3. **"OpenAI API error"**
   - Verify your `OPENAI_API_KEY` is valid
   - Check your OpenAI account has sufficient credits

4. **"Video too long"**
   - Check the `MAX_VIDEO_DURATION` setting
   - Consider processing shorter videos or increasing the limit

### Debug Mode

Enable debug mode by setting `DEBUG=true` in your environment to get more detailed error messages and logging.