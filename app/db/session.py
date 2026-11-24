"""Engine and session factory.

One synchronous SQLAlchemy session is yielded per request. Closing the session
does not commit: each owning service/caller must explicitly commit its writes.
SQLite connections enable foreign keys individually; production uses PostgreSQL.
"""

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    connect_args=(
        {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    ),
    pool_pre_ping=True,
)


def enable_sqlite_foreign_keys(target_engine: Engine) -> None:
    """SQLite ignores foreign keys unless the pragma is set per connection."""
    if target_engine.dialect.name != "sqlite":
        return

    @event.listens_for(target_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


enable_sqlite_foreign_keys(engine)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a request-owned session and close it; the owning service must commit mutations."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
