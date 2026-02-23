import os

# Gunicorn configuration file for a resource-constrained VPS (e.g., 1GB RAM)
# https://docs.gunicorn.org/en/stable/configure.html#configuration-file

# Bind to all network interfaces on port 8000.
bind = "0.0.0.0:8000"

# --- Worker Configuration ---
# Use the uvicorn worker class for FastAPI compatibility.
worker_class = "uvicorn.workers.UvicornWorker"

# --- Performance Tuning for Low-RAM Environment ---
#
# Number of Workers:
# Set to 1. On a 1GB RAM server, running more than one worker is risky
# and can easily lead to memory exhaustion, especially with a heavy app.
workers = int(os.getenv("WEB_CONCURRENCY", 1))
#
# Number of Threads:
# Use threads to handle multiple concurrent requests within the single worker.
# This is memory-efficient for I/O-bound tasks (like network requests).
# A value between 2-4 is a good starting point.
threads = int(os.getenv("WEB_THREADS", 4))

# --- Timeout Settings ---
#
# Timeout:
# Workers silent for more than this many seconds are killed and restarted.
# This is kept high (120s) because web scraping can be a slow process.
timeout = 120
#
# Keep-Alive:
# The number of seconds to wait for requests on a Keep-Alive connection.
keepalive = 5

# --- Logging ---
# Log to stdout and stderr, which is standard for containerized applications.
# accesslog = "-"
# errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# --- Process Naming ---
# Helps in identifying the process.
proc_name = "webtonotion"

# --- Server Mechanics ---
# Run in the foreground.
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None
