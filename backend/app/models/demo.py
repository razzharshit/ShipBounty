from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DemoPersona(Base):
    """Explicit, tenant-scoped identities allowed to use demo authentication."""

    __tablename__ = "demo_personas"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "persona",
            name="uq_demo_personas_organization_persona",
        ),
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_demo_personas_organization_user",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    persona: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    organization = relationship("Organization")
    user = relationship("User")
