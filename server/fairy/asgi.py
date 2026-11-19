"""ASGI entrypoint for PostgreSQL-backed Fairy."""

from .app import create_app

app = create_app()
