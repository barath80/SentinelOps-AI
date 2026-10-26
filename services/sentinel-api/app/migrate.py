"""Create the SentinelOps tables once: python -m app.migrate

Only creates missing tables; it does not alter existing ones. Before changing a column, add a
real migration tool (Alembic) rather than relying on this.
"""
from .config import get_settings
from .db import make_session_factory

if __name__ == "__main__":
    settings = get_settings()
    factory = make_session_factory(settings.database_url, create_schema=True)
    factory.kw["bind"].dispose()
    print("schema ok")
