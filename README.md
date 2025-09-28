# WebToNotion

A web scraping tool that converts web content to Notion pages using FastAPI and modern Python technologies.

## 🚀 Features

- **Web Scraping**: Extract content from web pages with advanced scraping capabilities
- **Notion Integration**: Seamlessly convert scraped content to Notion pages
- **FastAPI Backend**: Modern, fast, and async API built with FastAPI
- **Type Safety**: Full type annotations with mypy support
- **Modern Python**: Built with Python 3.12+ and latest best practices
- **Modular Architecture**: Clean, maintainable code structure

## 🛠️ Technology Stack

- **Python 3.12+**: Latest Python features and performance improvements
- **FastAPI**: Modern, fast web framework for building APIs
- **Pydantic**: Data validation using Python type annotations
- **SQLAlchemy**: SQL toolkit and Object-Relational Mapping
- **BeautifulSoup4**: Web scraping and HTML parsing
- **Uvicorn**: Lightning-fast ASGI server
- **Pytest**: Testing framework with async support
- **Ruff**: Fast Python linter and formatter

## 📋 Requirements

- Python 3.12 or higher
- pip (Python package installer)

## 🚀 Quick Start

### Installation

1. Clone the repository:
```bash
git clone https://github.com/MichalKus/WebToNotion.git
cd WebToNotion
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -e .
```

4. Install development dependencies (optional):
```bash
pip install -e ".[dev]"
```

### Running the Application

1. Start the FastAPI server:
```bash
webtonotion
```

Or run directly with uvicorn:
```bash
uvicorn webtonotion.main:app --reload
```

2. Open your browser and navigate to:
   - API Documentation: http://localhost:8000/docs
   - Alternative Docs: http://localhost:8000/redoc
   - Health Check: http://localhost:8000/health

## 🧪 Testing

Run the test suite:
```bash
pytest
```

Run tests with coverage:
```bash
pytest --cov=src --cov-report=html
```

## 🔧 Development

### Code Quality

This project uses several tools to maintain code quality:

- **Ruff**: For linting and formatting
- **MyPy**: For type checking
- **Pytest**: For testing

Run all quality checks:
```bash
# Linting and formatting
ruff check .
ruff format .

# Type checking
mypy src

# Tests
pytest
```

### Project Structure

```
WebToNotion/
├── src/webtonotion/          # Main application code
│   ├── controllers/          # API route handlers
│   ├── models/              # Data models
│   ├── services/            # Business logic
│   └── utils/               # Utility functions
├── tests/                   # Test suite
├── docs/                    # Documentation
├── config/                  # Configuration files
└── pyproject.toml          # Project metadata and dependencies
```

### Branching Strategy

- `main`: Production-ready code
- `develop`: Integration branch for features
- `feature/[name]`: Feature development branches
- `fix/[name]`: Bug fix branches

### Commit Convention

We follow Conventional Commits:
- `feat:` New features
- `fix:` Bug fixes
- `docs:` Documentation changes
- `style:` Code style changes
- `refactor:` Code refactoring
- `test:` Test additions or modifications
- `chore:` Build process or auxiliary tool changes

## 📝 Configuration

Create a `.env` file in the project root for local development:

```env
# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=true

# Notion Configuration
NOTION_API_KEY=your_notion_api_key_here
NOTION_DATABASE_ID=your_database_id_here

# Database Configuration (if using database)
DATABASE_URL=sqlite:///./webtonotion.db
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and quality checks
5. Commit your changes (`git commit -m 'feat: add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🔗 Links

- [Repository](https://github.com/MichalKus/WebToNotion)
- [Issues](https://github.com/MichalKus/WebToNotion/issues)
- [Documentation](https://github.com/MichalKus/WebToNotion#readme)

## 📞 Support

If you have any questions or need help, please:
1. Check the [documentation](docs/)
2. Search existing [issues](https://github.com/MichalKus/WebToNotion/issues)
3. Create a new issue if needed

---

Made with ❤️ by [MichalKus](https://github.com/MichalKus)