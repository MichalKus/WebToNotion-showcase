# Video Processing Guide

This guide provides detailed information about the video processing capabilities in WebToNotion, including setup, configuration, and usage.

## Overview

WebToNotion's video processing service provides comprehensive analysis of video content from various platforms, extracting metadata, transcribing audio, and performing AI-powered content analysis to create structured Notion pages.

## Architecture

The video processing pipeline consists of several components:

```
Video URL → URL Validation → Content Extraction → Audio Transcription → AI Analysis → Caching → Notion Integration
```

### Components

1. **VideoScrapingService**: Main service orchestrating the video processing pipeline
2. **yt-dlp Integration**: Primary tool for video metadata extraction and audio download
3. **OpenAI Whisper**: Audio transcription service
4. **PydanticAI Agents**: AI-powered content analysis
5. **Playwright Fallback**: Backup extraction method for difficult videos
6. **Caching System**: Intelligent caching of processed content

## Supported Platforms

The service supports video content from the following platforms:

- **YouTube** (`youtube.com`, `youtu.be`)
- **Vimeo** (`vimeo.com`)
- **Dailymotion** (`dailymotion.com`)
- **Twitch** (`twitch.tv`)
- **Facebook** (`facebook.com`)
- **Instagram** (`instagram.com`)

Additional platforms can be added by extending the URL validation logic in the `VideoScrapingService`.

## Setup and Configuration

### Prerequisites

1. **Python 3.12+**
2. **FFmpeg**: Required for audio processing
   ```bash
   # Windows (using chocolatey)
   choco install ffmpeg
   
   # macOS (using homebrew)
   brew install ffmpeg
   
   # Ubuntu/Debian
   sudo apt update && sudo apt install ffmpeg
   ```

3. **OpenAI API Key**: Required for transcription and AI analysis
4. **Notion API Key**: Required for creating Notion pages

### Environment Variables

Configure the following environment variables in your `.env` file:

```env
# Required
OPENAI_API_KEY=your_openai_api_key_here
NOTION_API_KEY=your_notion_integration_token_here

# Video Processing Configuration
CACHE_DIR=./cache                    # Directory for caching processed content
MAX_VIDEO_DURATION=3600              # Maximum video duration in seconds (1 hour)
ENABLE_CACHING=true                  # Enable/disable caching
WHISPER_MODEL=base                   # Whisper model size (tiny, base, small, medium, large)

# Optional Performance Settings
MAX_CONCURRENT_DOWNLOADS=3           # Maximum concurrent video downloads
AUDIO_QUALITY=best                   # Audio quality for transcription (best, good, medium)
CHUNK_SIZE=1024                      # Audio processing chunk size
```

### Whisper Model Selection

Choose the appropriate Whisper model based on your needs:

| Model | Size | Speed | Accuracy | Use Case |
|-------|------|-------|----------|----------|
| `tiny` | 39 MB | Fastest | Lowest | Quick testing, low-resource environments |
| `base` | 74 MB | Fast | Good | Default choice, balanced performance |
| `small` | 244 MB | Medium | Better | Higher accuracy requirements |
| `medium` | 769 MB | Slow | High | Professional transcription |
| `large` | 1550 MB | Slowest | Highest | Maximum accuracy, research use |

## Usage

### Basic Video Processing

```python
from webtonotion.services.video_scraping_service import VideoScrapingService

# Initialize the service
video_service = VideoScrapingService()

# Process a video URL
video_content = await video_service.process_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

print(f"Title: {video_content.title}")
print(f"Duration: {video_content.duration} seconds")
print(f"Topics: {video_content.topics}")
print(f"Sentiment: {video_content.sentiment}")
```

### API Usage

```bash
curl -X POST "http://localhost:8000/process/url" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "database_id": "your_notion_database_id",
    "custom_properties": {
      "source": "youtube",
      "category": "music"
    }
  }'
```

## Video Content Analysis

The AI analysis component extracts the following information from video content:

### Topics Extraction

Automatically identifies key topics and themes discussed in the video:

```python
# Example topics for a cooking video
topics = ["cooking", "recipe", "italian cuisine", "pasta", "ingredients"]
```

### Sentiment Analysis

Determines the overall emotional tone of the content:

- `positive`: Upbeat, encouraging, or positive content
- `negative`: Critical, sad, or negative content
- `neutral`: Informational or balanced content

### Location Detection

Identifies geographical locations mentioned in the video:

```python
# Example locations for a travel video
locations = ["Paris", "France", "Eiffel Tower", "Seine River"]
```

### Metadata Extraction

Captures comprehensive video metadata:

```python
{
    "title": "How to Make Perfect Pasta",
    "description": "Learn the secrets of authentic Italian pasta...",
    "author": "Chef Mario",
    "duration": 480,  # seconds
    "published_at": "2024-01-15T10:30:00",
    "quality": "1080p",
    "language": "en",
    "view_count": 125000,
    "like_count": 3500
}
```

## Caching System

The caching system improves performance and reduces API costs by storing processed content.

### Cache Structure

```
cache/
├── videos/
│   ├── {md5_hash}/
│   │   ├── metadata.json      # Video metadata
│   │   ├── transcript.txt     # Full transcript
│   │   ├── analysis.json      # AI analysis results
│   │   └── audio.wav         # Downloaded audio (optional)
```

### Cache Management

```python
# Check if video is cached
is_cached = video_service._get_cached_content(cache_key)

# Clear cache for a specific video
video_service._clear_cache(cache_key)

# Clear all cache
import shutil
shutil.rmtree("./cache")
```

### Cache Configuration

```env
# Enable/disable caching
ENABLE_CACHING=true

# Cache directory
CACHE_DIR=./cache

# Cache expiration (in seconds, 0 = never expire)
CACHE_EXPIRATION=86400  # 24 hours
```

## Error Handling

The video processing service implements comprehensive error handling:

### Common Exceptions

```python
from webtonotion.exceptions import (
    VideoScrapingError,
    VideoDownloadError,
    TranscriptionError,
    PlaywrightFallbackError
)

try:
    video_content = await video_service.process_video(url)
except VideoDownloadError as e:
    print(f"Failed to download video: {e}")
except TranscriptionError as e:
    print(f"Failed to transcribe audio: {e}")
except VideoScrapingError as e:
    print(f"General video processing error: {e}")
```

### Error Recovery

The service implements several fallback mechanisms:

1. **Playwright Fallback**: If yt-dlp fails, try Playwright-based extraction
2. **Quality Degradation**: If high-quality audio fails, try lower quality
3. **Partial Processing**: Return available data even if some steps fail
4. **Retry Logic**: Automatic retries for transient failures

## Performance Optimization

### Concurrent Processing

```python
# Process multiple videos concurrently
import asyncio

urls = [
    "https://www.youtube.com/watch?v=video1",
    "https://www.youtube.com/watch?v=video2",
    "https://www.youtube.com/watch?v=video3"
]

tasks = [video_service.process_video(url) for url in urls]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

### Memory Management

For large videos or batch processing:

```env
# Limit memory usage
MAX_AUDIO_SIZE=100MB
TEMP_DIR=/tmp/webtonotion
CLEANUP_TEMP_FILES=true
```

### Processing Limits

```env
# Set processing limits
MAX_VIDEO_DURATION=3600      # 1 hour maximum
MAX_FILE_SIZE=500MB          # 500MB maximum download
MAX_CONCURRENT_JOBS=5        # Maximum concurrent processing jobs
```

## Monitoring and Logging

The service provides comprehensive logging for monitoring and debugging:

### Log Levels

```python
import logging

# Set log level
logging.getLogger("webtonotion.services.video_scraping_service").setLevel(logging.DEBUG)
```

### Key Metrics

The service logs the following metrics:

- Processing time per video
- Cache hit/miss rates
- API usage statistics
- Error rates by type
- Resource usage (memory, disk)

### Integration with Logfire

```python
# Logfire integration for monitoring
import logfire

logfire.info(
    "Video processed successfully",
    video_url=url,
    duration=video_content.duration,
    processing_time=elapsed_time
)
```

## Testing

### Unit Tests

```bash
# Run video processing unit tests
pytest tests/unit/test_video_scraping_service.py -v

# Run with coverage
pytest tests/unit/test_video_scraping_service.py --cov=webtonotion.services.video_scraping_service
```

### Integration Tests

```bash
# Run integration tests (requires API keys)
pytest tests/integration/test_video_scraping_integration.py -m "requires_api_keys"

# Skip slow tests
pytest tests/integration/test_video_scraping_integration.py -m "not slow"
```

### Test Configuration

```python
# pytest.ini or pyproject.toml
[tool.pytest.ini_options]
markers = [
    "integration: marks tests as integration tests",
    "slow: marks tests as slow running",
    "requires_api_keys: marks tests that require API keys",
    "requires_internet: marks tests that require internet connection"
]
```

## Troubleshooting

### Common Issues

#### 1. FFmpeg Not Found

```
Error: FFmpeg not found. Please install FFmpeg.
```

**Solution**: Install FFmpeg using your system's package manager.

#### 2. OpenAI API Rate Limit

```
Error: OpenAI API rate limit exceeded
```

**Solution**: 
- Implement exponential backoff
- Use a smaller Whisper model
- Reduce concurrent processing

#### 3. Video Not Accessible

```
Error: Video is private or unavailable
```

**Solution**:
- Verify the video URL is correct and public
- Check if the platform is supported
- Try the URL in a browser first

#### 4. Large Video Processing

```
Error: Video exceeds maximum duration limit
```

**Solution**:
- Increase `MAX_VIDEO_DURATION` setting
- Process video in chunks
- Use a more efficient Whisper model

#### 5. Cache Issues

```
Error: Permission denied writing to cache directory
```

**Solution**:
- Check directory permissions
- Ensure `CACHE_DIR` is writable
- Clear corrupted cache files

### Debug Mode

Enable detailed debugging:

```env
DEBUG=true
LOG_LEVEL=DEBUG
VERBOSE_LOGGING=true
```

### Performance Profiling

```python
import cProfile
import pstats

# Profile video processing
profiler = cProfile.Profile()
profiler.enable()

video_content = await video_service.process_video(url)

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 functions
```

## Best Practices

### 1. Resource Management

- Use appropriate Whisper model for your use case
- Implement proper cleanup of temporary files
- Monitor memory usage for large videos

### 2. Error Handling

- Always handle exceptions gracefully
- Implement retry logic for transient failures
- Log errors with sufficient context

### 3. Caching Strategy

- Enable caching for production use
- Regularly clean up old cache files
- Monitor cache hit rates

### 4. API Usage

- Respect rate limits of external services
- Implement exponential backoff
- Use batch processing when possible

### 5. Security

- Validate URLs before processing
- Sanitize file paths and names
- Don't log sensitive information

## Advanced Configuration

### Custom AI Analysis

Extend the AI analysis capabilities:

```python
from pydantic_ai import Agent
from webtonotion.models.video import VideoContent

# Custom analysis agent
custom_agent = Agent(
    'openai:gpt-4',
    result_type=dict,
    system_prompt="Analyze video content for specific domain knowledge..."
)

# Use in video processing
async def custom_analysis(transcript: str) -> dict:
    result = await custom_agent.run(transcript)
    return result.data
```

### Platform-Specific Extractors

Add support for new platforms:

```python
class CustomPlatformExtractor:
    def is_supported(self, url: str) -> bool:
        return "customplatform.com" in url
    
    async def extract_metadata(self, url: str) -> dict:
        # Custom extraction logic
        pass
```

### Webhook Integration

Set up webhooks for processing notifications:

```python
from fastapi import BackgroundTasks

async def process_video_with_webhook(
    url: str,
    webhook_url: str,
    background_tasks: BackgroundTasks
):
    # Process video in background
    background_tasks.add_task(
        process_and_notify,
        url,
        webhook_url
    )
```

This guide provides a comprehensive overview of the video processing capabilities in WebToNotion. For additional support or questions, please refer to the project documentation or create an issue on GitHub.