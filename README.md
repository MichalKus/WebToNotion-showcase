# WebToNotion

AI-powered URL processing for Notion integration. A FastAPI application that processes URLs from social media platforms, extracts structured information using AI agents, and intelligently creates Notion pages in appropriate databases.

## 🚀 Features

- **AI-Powered Processing**: Uses PydanticAI agents to intelligently analyze content
- **Social Media Support**: Specialized handling for YouTube, Facebook, and Instagram
- **Smart Notion Integration**: Automatically selects the most appropriate Notion database
- **Web Scraping**: Robust content extraction with Playwright for dynamic content
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
- Logfire account (optional, for monitoring)

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
   SECRET_KEY=your_secret_key_here_change_in_production
   
   # Optional
   LOGFIRE_TOKEN=your_logfire_token_here
   DEBUG=true
   LOG_LEVEL=INFO
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

### API Endpoints

#### Process URL
```http
POST /api/v1/process-url
Content-Type: application/json

{
  "url": "https://www.instagram.com/p/example/"
}
```

**Response**:
```json
{
  "status": "success",
  "message": "Successfully processed and added to Notion.",
  "notion_page_url": "https://www.notion.so/..."
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
│   ├── models/                # Pydantic data models
│   ├── config/                # Configuration management
│   └── main.py               # Application entry point
├── tests/                     # Test suite
│   ├── unit/                  # Unit tests
│   └── integration/           # Integration tests
├── docs/                      # Documentation
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