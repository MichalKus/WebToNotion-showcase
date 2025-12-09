# Video Scraping Service Refactoring Proposal

## 1. Current Structure Assessment

The file `src/webtonotion/services/video_scraping_service.py` currently contains a monolithic service class `VideoScrapingService` and two internal Pydantic models. It handles multiple distinct responsibilities including video extraction, audio processing, transcription, content analysis, and caching.

### Functions and Methods Analysis

**Class: `VideoScrapingService`**

| Method | Purpose |
|--------|---------|
| `__init__` | Initializes clients (OpenAI), directories, configuration, and AI agents. |
| `process_video` | Main public entry point. Orchestrates the flow: Check Cache -> Extract (yt-dlp/Playwright) -> Cache -> Return. |
| `_extract_with_ytdlp` | Core logic for yt-dlp extraction. Handles metadata extraction, duration checks, audio download orchestration, transcription orchestration, and analysis orchestration. |
| `_extract_with_playwright` | Fallback extraction using Playwright (browsing, DOM scraping). |
| `_download_audio` | Uses yt-dlp to download audio and `pydub` to convert/format it. |
| `_transcribe_audio` | Uses `transcription_agent` (PydanticAI) to transcribe audio files. |
| `_analyze_content` | Uses `analysis_agent` (PydanticAI) to generate structured insights from metadata and transcript. |
| `_create_video_content_without_transcript` | Variant of processing for videos exceeding duration limits. |
| `_get_cache_key` | Generates MD5 hash of URL for caching. |
| `_get_cached_content` | Retrieves and deserializes cached JSON data. |
| `_cache_content` | Serializes and saves content to JSON file. |
| `_parse_file_size` | Helper to convert size strings (MB/GB) to bytes. |
| `_get_audio_quality_value` | Helper to map quality strings to yt-dlp integers. |
| `_parse_upload_date` | Helper to parse date strings. |
| `_detect_platform` | Helper to identify platform from URL. |
| `_extract_title_with_playwright` | Playwright DOM helper. |
| `_extract_description_with_playwright` | Playwright DOM helper. |
| `_extract_author_with_playwright` | Playwright DOM helper. |

### Classes and Models

| Name | Type | Location | Responsibility |
|------|------|----------|----------------|
| `ContentAnalysisResult` | Pydantic Model | Lines 28-54 | Defines structure for AI analysis (topics, sentiment, locations, etc.). |
| `TranscriptionResult` | Pydantic Model | Lines 56-77 | Defines structure for transcription output (text, confidence, language). |
| `VideoScrapingService` | Class | Lines 79+ | Main service class handling all scraping and processing logic. |

### Code Smells and SOLID Violations

1.  **Single Responsibility Principle (SRP) Violation**:
    *   `VideoScrapingService` is a "God Class" responsible for:
        *   Web Scraping (yt-dlp, Playwright)
        *   File System Operations (Caching, Temp files)
        *   Audio Processing (Conversion, format handling)
        *   AI Integration (Transcription, Analysis)
        *   Configuration Parsing
    *   **Evidence**: The `__init__` method sets up dependencies for *all* these concerns.

2.  **Separation of Concerns**:
    *   Data models (`ContentAnalysisResult`, `TranscriptionResult`) are defined inside the service file instead of the `models` module.
    *   Low-level DOM selectors (Playwright) are mixed with high-level orchestration logic.

3.  **Open/Closed Principle (OCP)**:
    *   Adding a new extraction method (e.g., a generic scraper) requires modifying the `VideoScrapingService` class.
    *   Changing the storage mechanism (e.g., from file-based cache to Redis) requires modifying the service.

4.  **Coupling**:
    *   The service is tightly coupled to specific libraries (`yt_dlp`, `playwright`, `pydub`, `openai`).

## 2. Proposed Modularization Approach

We recommend breaking down `VideoScrapingService` into smaller, focused services and moving models to their appropriate location.

### Recommended File Structure

```
src/webtonotion/
├── models/
│   └── video.py           # Add ContentAnalysisResult and TranscriptionResult here
├── services/
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── content_analyzer.py  # Handles AI analysis (was _analyze_content)
│   │   └── transcriber.py       # Handles Audio transcription (was _transcribe_audio)
│   ├── extraction/
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract Base Class for extractors
│   │   ├── ytdlp_extractor.py   # yt-dlp implementation
│   │   └── playwright_extractor.py # Playwright implementation
│   ├── storage/
│   │   ├── __init__.py
│   │   └── file_cache.py        # Handles caching logic
│   └── video_scraping_service.py # Orchestrator (much smaller)
```

### Logical Grouping

1.  **Models**: Move `ContentAnalysisResult` and `TranscriptionResult` to `src/webtonotion/models/video.py`.
2.  **AI Services**: Group `transcription_agent` and `analysis_agent` logic into dedicated classes in `services/analysis/`.
3.  **Extraction Strategies**: Isolate `yt-dlp` and `Playwright` logic into separate classes implementing a common interface.
4.  **Infrastructure**: Move file-based caching to a dedicated `FileCacheService`.

## 3. Clean Code Improvements

### Single Responsibility Principle Implementation

*   **`ContentAnalyzer`**: Responsible solely for taking text/metadata and producing a `ContentAnalysisResult`.
*   **`AudioTranscriber`**: Responsible solely for taking an audio file path and producing a `TranscriptionResult`.
*   **`YtDlpExtractor`**: Responsible solely for interacting with `yt-dlp` to get metadata and audio files.
*   **`PlaywrightExtractor`**: Responsible solely for browser automation to get metadata.
*   **`VideoScrapingService`**: Becomes a **Coordinator/Facade**. It simply calls the extractor, then the transcriber, then the analyzer, and handles caching.

### Interface/Abstraction Opportunities

Define an abstract base class for extractors:

```python
from abc import ABC, abstractmethod

class VideoExtractor(ABC):
    @abstractmethod
    async def extract(self, url: str) -> VideoExtractionResult:
        pass
```

This allows easy addition of new extractors (e.g., specific support for Twitter/X API) without changing the main service.

### Error Handling Strategy

*   Create specific exceptions for each subdomain: `ExtractionError`, `TranscriptionError`, `AnalysisError`.
*   The main service catches these specific errors and wraps them in a high-level `VideoProcessingError` (or keeps `VideoScrapingError`) to provide a unified API response.

## 4. Impact Analysis

### Expected Benefits

*   **Maintainability**: Smaller files are easier to read and debug.
*   **Testability**: Each component (Analyzer, Transcriber, Extractor) can be unit tested in isolation with mocks. Currently, testing `VideoScrapingService` requires mocking a complex chain of dependencies.
*   **Extensibility**: Adding support for new platforms or changing AI models becomes a configuration change or a new class implementation rather than a modification of existing complex logic.
*   **Reusability**: The `AudioTranscriber` could be reused for other features (e.g., voice notes) independent of video scraping.

### Potential Migration Challenges

*   **Refactoring Effort**: Requires moving significant chunks of code and ensuring imports are updated.
*   **Dependency Injection**: The main `VideoScrapingService` will need to instantiate or receive instances of the new sub-services.
*   **State Management**: `yt-dlp` options and temp directory management need to be correctly passed to the `YtDlpExtractor`.

### Backward Compatibility

*   The public API `VideoScrapingService.process_video(url)` signature should remain **unchanged**. This ensures that `main.py` or other consumers do not need to be updated immediately.
*   The return type `VideoContent` remains the same.
