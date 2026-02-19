# WebToNotion

AI-powered URL processing for Notion integration. A FastAPI application that processes URLs from social media platforms and video content, extracts structured information using AI agents, and intelligently creates Notion pages in appropriate databases.

## 🚀 Features

- **AI-Powered Processing**: Uses PydanticAI agents to intelligently analyze content
- **Video Content Processing**: Advanced video scraping with yt-dlp, audio transcription, and AI analysis
- **Social Media Support**: Specialized handling for YouTube, Facebook, and Instagram
- **Smart Notion Integration**: Automatically selects the most appropriate Notion database
- **Web Scraping**: Robust content extraction with Playwright for dynamic content
- **Audio Transcription**: OpenAI Whisper integration for video-to-text conversion
- **Content Analysis**: AI-powered topic extraction, sentiment analysis, and location detection
- **Caching System**: Intelligent caching for processed video content
- **Monitoring & Observability**: Integrated with Logfire for comprehensive monitoring
- **Modern Architecture**: Built with FastAPI, Pydantic, and async/await patterns

## 🏗️ Architecture

The application follows a modular, service-oriented architecture:

- **API Layer**: FastAPI endpoints for URL processing
- **Core Agent**: PydanticAI-powered orchestration logic
- **Services Layer**: Web scraping, Notion integration, and monitoring services
- **Models**: Pydantic models for data validation and serialization
- **Configuration**: Environment-based settings management

## 📋 Prerequisites

- Python 3.12+
- Notion API integration token
- OpenAI API key (for video transcription and content analysis)
- Logfire account (optional, for monitoring)
- FFmpeg (for audio processing)

## 🛠️ Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/MichalKus/WebToNotion.git
   cd WebToNotion
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -e .
   ```

4. **Install development dependencies** (optional):
   ```bash
   pip install -e ".[dev]"
   ```

5. **Install Playwright browsers**:
   ```bash
   playwright install
   ```

## ⚙️ Configuration

1. **Copy the environment template**:
   ```bash
   cp .env.example .env
   ```

2. **Configure your environment variables** in `.env`:
   ```env
   # Required
   NOTION_API_KEY=your_notion_integration_token_here
   OPENAI_API_KEY=your_openai_api_key_here
   SECRET_KEY=your_secret_key_here_change_in_production
   
   # Optional
   LOGFIRE_TOKEN=your_logfire_token_here
   DEBUG=true
   LOG_LEVEL=INFO
   
   # Video Processing Configuration
   CACHE_DIR=./cache
   MAX_VIDEO_DURATION=3600  # Maximum video duration in seconds (1 hour)
   ENABLE_CACHING=true
   ```

3. **Set up Notion Integration**:
   - Go to [Notion Integrations](https://www.notion.so/my-integrations)
   - Create a new integration
   - Copy the integration token to your `.env` file
   - Share your Notion databases with the integration

## 🚀 Usage

### Running the Application

**Development mode**:
```bash
python -m webtonotion.main
```

**Production mode**:
```bash
uvicorn webtonotion.main:create_app --host 0.0.0.0 --port 8000
```

### 🐳 Docker

**Build the image**:
```bash
docker build -t webtonotion -f docker/Dockerfile .
```

**Run the container**:
```bash
docker run -d \
  -p 8000:8000 \
  --env-file .env \
  --name webtonotion \
  webtonotion
```

The Docker configuration uses Gunicorn with Uvicorn workers, optimized for production environments.

### ☁️ Deployment to VPS

Deploying to a VPS (Virtual Private Server) is streamlined using Docker Compose.

**Prerequisites**:
- A VPS with SSH access.
- [Docker](https://docs.docker.com/engine/install/) and [Docker Compose](https://docs.docker.com/compose/install/) installed on the server.

**Step-by-Step Guide**:

1. **Connect to your VPS**:
   ```bash
   ssh user@your-vps-ip
   ```

2. **Prepare the directory**:
   ```bash
   mkdir -p webtonotion
   cd webtonotion
   ```

3. **Transfer project files**:
   You can clone the repository or use `rsync`/`scp` to copy files from your local machine.
   ```bash
   git clone https://github.com/MichalKus/WebToNotion.git .
   # OR use rsync from local machine:
   # rsync -avz --exclude 'venv' . user@your-vps-ip:~/webtonotion/
   ```

4. **Configure Environment**:
   Create a `.env` file with your production secrets:
   ```bash
   nano .env
   ```
   Ensure you set `COOKIES_FILE_PATH` (default: `/app/cookies.txt`) and other necessary variables.

5. **Start the Service**:
   Use the Docker Compose configuration located in the `docker` directory:
   ```bash
   docker-compose -f docker/docker-compose.yaml up -d
   ```
   This pulls the pre-built image `mikus67/webtonotion-vps` and starts the services.

6. **Verify Deployment**:
   ```bash
   docker-compose -f docker/docker-compose.yaml ps
   curl http://localhost:8000/api/v1/health
   ```

### API Endpoints

#### Process URL
Process any supported URL (video or web content) and create a Notion page.

```http
POST /process/url
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "database_id": "your_notion_database_id",
  "custom_properties": {
    "source": "youtube",
    "priority": "high"
  }
}
```

**Response for Video Content**:
```json
{
  "success": true,
  "message": "Video URL processed successfully",
  "page_id": "page_123",
  "page_url": "https://notion.so/page_123",
  "content_type": "video",
  "video_details": {
    "title": "Never Gonna Give You Up",
    "author": "Rick Astley",
    "duration": 212,
    "published_at": "2009-10-25T00:00:00",
    "topics": ["music", "80s", "pop"],
    "sentiment": "positive",
    "transcript_preview": "Never gonna give you up, never gonna let you down..."
  }
}
```

**Response for Non-Video Content**:
```json
{
  "success": false,
  "message": "Non-video URL processing not yet implemented",
  "content_type": "web_page",
  "url": "https://example.com/article"
}
```

#### Processing Status
Check the current status of processing capabilities.

```http
GET /process/status
```

**Response**:
```json
{
  "video_scraping": "available",
  "web_scraping": "not_implemented",
  "notion_integration": "available",
  "ai_agents": "available",
  "supported_video_platforms": [
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "dailymotion.com",
    "twitch.tv"
  ]
}
```

#### Health Check
```http
GET /health
```

**Response**:
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "service": "WebToNotion"
}
```

## 🧪 Testing

**Run all tests**:
```bash
pytest
```

**Run with coverage**:
```bash
pytest --cov=webtonotion --cov-report=html
```

**Run specific test types**:
```bash
# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/

# Video processing tests only
pytest tests/ -k "video"

# Skip slow tests
pytest tests/ -m "not slow"

# Skip tests requiring API keys
pytest tests/ -m "not requires_api_keys"
```

## 🔧 Development

### Code Quality

**Format code**:
```bash
black src/ tests/
isort src/ tests/
```

**Type checking**:
```bash
mypy src/
```

**Linting**:
```bash
flake8 src/ tests/
```

### Pre-commit Hooks

Install pre-commit hooks for automatic code quality checks:
```bash
pre-commit install
```

## 📁 Project Structure

```
WebToNotion/
├── src/webtonotion/           # Main application package
│   ├── api/                   # FastAPI routers and endpoints
│   ├── core/                  # Core business logic and AI agents
│   ├── services/              # External service integrations
│   │   ├── notion_service.py  # Notion API integration
│   │   └── video_scraping_service.py  # Video processing service
│   ├── models/                # Pydantic data models
│   │   ├── request.py         # API request models
│   │   ├── response.py        # API response models
│   │   └── video.py          # Video content models
│   ├── config/                # Configuration management
│   │   ├── settings.py        # Application settings
│   │   └── logging.py         # Logging configuration
│   ├── utils/                 # Utility functions
│   ├── exceptions.py          # Custom exception classes
│   ├── dependencies.py        # FastAPI dependency injection
│   └── main.py               # Application entry point
├── tests/                     # Test suite
│   ├── unit/                  # Unit tests
│   │   ├── test_video_scraping_service.py
│   │   └── test_api_process.py
│   ├── integration/           # Integration tests
│   │   ├── test_video_scraping_integration.py
│   │   └── test_api_process_integration.py
│   └── conftest.py           # Pytest configuration and fixtures
├── docs/                      # Documentation
│   ├── architecture/          # Architecture documentation
│   └── diagrams/             # System diagrams
├── cache/                     # Video processing cache (created at runtime)
├── pyproject.toml            # Project configuration
├── .env.example              # Environment variables template
└── README.md                 # This file
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and ensure code quality
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Issues**: [GitHub Issues](https://github.com/MichalKus/WebToNotion/issues)
- **Documentation**: [Project Documentation](docs/)
- **Discussions**: [GitHub Discussions](https://github.com/MichalKus/WebToNotion/discussions)

## 🙏 Acknowledgments

- [FastAPI](https://fastapi.tiangolo.com/) for the excellent web framework
- [PydanticAI](https://ai.pydantic.dev/) for AI agent capabilities
- [Notion API](https://developers.notion.com/) for database integration
- [Playwright](https://playwright.dev/) for web scraping capabilities
- [Logfire](https://logfire.pydantic.dev/) for monitoring and observability