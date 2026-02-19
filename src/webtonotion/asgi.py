"""ASGI entry point for the application.

This module exposes the ASGI application object for use by WSGI servers
like Gunicorn (with Uvicorn workers).
"""

from webtonotion.main import create_app

app = create_app()
