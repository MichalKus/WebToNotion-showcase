# Stage 1: Builder
# We use the slim-bookworm image for a smaller footprint.
FROM python:3.12-slim-bookworm as builder

# Prevent python from writing pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies in a single layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install build tools
RUN pip install --no-cache-dir --upgrade pip build wheel setuptools

# Copy project definition and source code
COPY pyproject.toml README.md ./
RUN mkdir -p src && touch src/__init__.py

RUN pip install --no-cache-dir .

COPY src ./src

# Install dependencies. gunicorn is included for production.
RUN pip install --no-cache-dir --no-deps .

# Stage 2: Production
# Start with the same slim-bookworm base for consistency.
FROM python:3.12-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install only essential runtime dependencies.
# curl is kept for the healthcheck.
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libavcodec-extra \
    curl \
    unzip \
    ca-certificates \
    && curl -fsSL https://deno.land/install.sh | sh \
    && mv /root/.deno/bin/deno /usr/local/bin/ \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Ustaw PATH jeśli potrzeba
# ENV PATH="/root/.deno/bin:${PATH}"

# Copy the virtual environment from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Create a non-root user for security.
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy the Gunicorn configuration.
COPY docker/gunicorn_conf.py .

# Copy cookies file if it exists
COPY tmp/cookies.txt /app/cookies.txt

# Create and set permissions for cache/log directories.
RUN mkdir -p /app/cache /app/logs /app/temp && chown -R appuser:appuser /app

# Set proper permissions for cookies file if it exists
RUN if [ -f /app/cookies.txt ]; then chmod 644 /app/cookies.txt && chown appuser:appuser /app/cookies.txt; fi

# Set ownership of the entire app directory.
RUN chown -R appuser:appuser /app

# Switch to the non-root user.
USER appuser

# Expose the application port.
EXPOSE 8000

# Healthcheck to ensure the application is running.
# HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
#     CMD curl -f http://localhost:8000/api/v1/health/ || exit 1

# Set default environment variables.
ENV PORT=8000
ENV HOST=0.0.0.0
ENV ENVIRONMENT=production

# Run the application with the VPS-optimized Gunicorn config.
CMD ["gunicorn", "-c", "gunicorn_conf.py", "webtonotion.asgi:app"]
