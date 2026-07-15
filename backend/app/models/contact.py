"""Domain-neutral contact and account-scoped channel identity models."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    display_name: Mapped[str | None] = mapped_column(String(160))
    primary_email: Mapped[str | None] = mapped_column(String(254))
    primary_phone: Mapped[str | None] = mapped_column(String(32))
    avatar_url: Mapped[str | None] = mapped_column(String)
    locale: Mapped[str | None] = mapped_column(String(35))
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    channel_identities: Mapped[list["ContactChannelIdentity"]] = relationship(
        lazy="selectin", order_by="ContactChannelIdentity.created_at"
    )

    @property
    def primary_channel(self) -> "ContactChannelIdentity | None":
        return self.channel_identities[0] if self.channel_identities else None


class ContactChannelIdentity(Base):
    __tablename__ = "contact_channel_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider", "account_key", "external_id", name="uq_contact_channel_authority"
        ),
        UniqueConstraint("id", "contact_id", name="uq_contact_channel_contact"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    account_key: Mapped[str] = mapped_column(String(128), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
