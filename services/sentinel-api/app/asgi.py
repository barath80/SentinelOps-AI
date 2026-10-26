"""Entry point for the server: `uvicorn app.asgi:app`."""
from .main import create_app

app = create_app()
