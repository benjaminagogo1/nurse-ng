"""Declarative base and shared columns.

All model IDs and timestamp mixins originate here. SQLAlchemy metadata is
assembled by app.models; existing installations evolve through Alembic revisions.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.uuid import uuid7


class Base(DeclarativeBase):
    """Shared SQLAlchemy metadata root; import app.models before migration metadata inspection."""
    pass


class TimestampMixin:
    """Database-created creation/update timestamps reused by persisted domain records."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class UUIDPrimaryKeyMixin:
    """UUIDv7 primary key.

    Licence numbers, registration numbers, and national identity numbers are
    never primary keys or public identifiers.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid7,
    )
