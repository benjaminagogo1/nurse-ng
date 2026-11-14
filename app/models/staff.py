"""Administrative role changes retain who made the decision and when."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.models.user import User


class StaffRoleEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "staff_role_events"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id])
    target: Mapped[User | None] = relationship(foreign_keys=[target_id])
