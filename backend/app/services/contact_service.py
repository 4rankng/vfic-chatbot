"""Contact persistence, visibility, and race-safe channel identity resolution."""

from __future__ import annotations

import uuid

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case
from app.models.contact import Contact, ContactChannelIdentity
from app.models.conversation import Conversation
from app.models.user import Role, User
from app.schemas.contacts import ChannelIdentityCreate, ContactCreate, ContactUpdate
from app.services.audit_service import record_audit
from app.services.errors import ConflictError, NotFoundError


class ContactService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _visible(user: User):
        if user.role == Role.admin:
            return True
        return or_(
            exists(
                select(1).where(
                    Conversation.contact_id == Contact.id,
                    or_(
                        Conversation.assigned_recruiter_id.is_(None),
                        Conversation.assigned_recruiter_id == user.id,
                    ),
                )
            ),
            exists(
                select(1).where(
                    Case.contact_id == Contact.id,
                    or_(Case.assigned_user_id.is_(None), Case.assigned_user_id == user.id),
                )
            ),
        )

    async def list(
        self,
        *,
        viewer: User,
        page: int,
        per_page: int,
        q: str | None,
        provider: str | None,
        account_key: str | None,
        external_id: str | None,
        sort_by: str | None,
        order: str,
    ) -> tuple[list[Contact], int]:
        query = select(Contact).where(self._visible(viewer))
        if q:
            pattern = f"%{q}%"
            query = query.where(
                or_(
                    Contact.display_name.ilike(pattern),
                    Contact.primary_email.ilike(pattern),
                    Contact.primary_phone.ilike(pattern),
                )
            )
        if provider or account_key or external_id:
            query = query.where(
                exists(
                    select(1).where(
                        ContactChannelIdentity.contact_id == Contact.id,
                        *((ContactChannelIdentity.provider == provider,) if provider else ()),
                        *(
                            (ContactChannelIdentity.account_key == account_key,)
                            if account_key
                            else ()
                        ),
                        *(
                            (ContactChannelIdentity.external_id == external_id,)
                            if external_id
                            else ()
                        ),
                    )
                )
            )
        total = int(await self.db.scalar(select(func.count()).select_from(query.subquery())) or 0)
        sort_columns = {
            "created_at": Contact.created_at,
            "updated_at": Contact.updated_at,
            "display_name": Contact.display_name,
        }
        column = sort_columns.get(sort_by or "updated_at", Contact.updated_at)
        query = (
            query.order_by(column.asc() if order == "asc" else column.desc(), Contact.id)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        return list(await self.db.scalars(query)), total

    async def get_visible(self, contact_id: uuid.UUID, viewer: User) -> Contact:
        contact = await self.db.scalar(
            select(Contact).where(Contact.id == contact_id, self._visible(viewer))
        )
        if contact is None:
            raise NotFoundError("contact not found")
        return contact

    async def lock_visible_anchor(self, contact_id: uuid.UUID, viewer: User) -> None:
        """Lock one recruiter-visible authority row through the caller's commit."""
        if viewer.role == Role.admin:
            return
        case_id = await self.db.scalar(
            select(Case.id)
            .where(
                Case.contact_id == contact_id,
                or_(Case.assigned_user_id.is_(None), Case.assigned_user_id == viewer.id),
            )
            .order_by(Case.id)
            .limit(1)
            .with_for_update(read=True)
        )
        if case_id is not None:
            return
        conversation_id = await self.db.scalar(
            select(Conversation.id)
            .where(
                Conversation.contact_id == contact_id,
                or_(
                    Conversation.assigned_recruiter_id.is_(None),
                    Conversation.assigned_recruiter_id == viewer.id,
                ),
            )
            .order_by(Conversation.id)
            .limit(1)
            .with_for_update(read=True)
        )
        if conversation_id is None:
            raise NotFoundError("contact not found")

    async def identities(self, contact_id: uuid.UUID) -> list[ContactChannelIdentity]:
        return list(
            await self.db.scalars(
                select(ContactChannelIdentity)
                .where(ContactChannelIdentity.contact_id == contact_id)
                .order_by(ContactChannelIdentity.created_at, ContactChannelIdentity.id)
            )
        )

    async def create(self, body: ContactCreate, actor: User) -> Contact:
        contact = Contact(**body.model_dump(exclude={"channel_identities"}, mode="python"))
        self.db.add(contact)
        await self.db.flush()
        try:
            for item in body.channel_identities:
                self.db.add(ContactChannelIdentity(contact_id=contact.id, **item.model_dump()))
            await record_audit(
                self.db,
                action="create_contact",
                actor_id=actor.id,
                target_type="contact",
                target_id=str(contact.id),
            )
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError("channel identity already belongs to another contact") from exc
        await self.db.refresh(contact)
        return contact

    async def update(self, contact: Contact, body: ContactUpdate, actor: User) -> Contact:
        values = body.model_dump(exclude={"version"}, exclude_unset=True, mode="python")
        result = await self.db.execute(
            update(Contact)
            .where(
                Contact.id == contact.id,
                Contact.version == body.version,
                self._visible(actor),
            )
            .values(**values, version=Contact.version + 1, updated_at=func.now())
            .returning(Contact)
        )
        updated = result.scalar_one_or_none()
        if updated is None:
            still_visible = await self.db.scalar(
                select(exists().where(Contact.id == contact.id, self._visible(actor)))
            )
            if not still_visible:
                raise NotFoundError("contact not found")
            raise ConflictError("contact changed since it was loaded")
        await record_audit(
            self.db,
            action="update_contact",
            actor_id=actor.id,
            target_type="contact",
            target_id=str(contact.id),
            payload={"fields": sorted(values)},
        )
        await self.db.commit()
        return updated

    async def attach_identity(
        self, contact: Contact, body: ChannelIdentityCreate, actor: User
    ) -> ContactChannelIdentity:
        identity = ContactChannelIdentity(contact_id=contact.id, **body.model_dump())
        self.db.add(identity)
        try:
            await self.db.flush()
            await record_audit(
                self.db,
                action="attach_contact_channel_identity",
                actor_id=actor.id,
                target_type="contact",
                target_id=str(contact.id),
                payload={
                    "identity_id": str(identity.id),
                    "provider": identity.provider,
                    "account_key": identity.account_key,
                },
            )
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError("channel identity already belongs to a contact") from exc
        await self.db.refresh(identity)
        return identity

    async def resolve_channel_identity(
        self,
        *,
        provider: str,
        account_key: str,
        external_id: str,
        actor_id: uuid.UUID | None = None,
    ) -> ContactChannelIdentity:
        identity = await self.db.scalar(
            select(ContactChannelIdentity).where(
                ContactChannelIdentity.provider == provider,
                ContactChannelIdentity.account_key == account_key,
                ContactChannelIdentity.external_id == external_id,
            )
        )
        if identity is not None:
            return identity
        savepoint = await self.db.begin_nested()
        contact = Contact()
        identity = ContactChannelIdentity(
            contact_id=contact.id,
            provider=provider,
            account_key=account_key,
            external_id=external_id,
        )
        try:
            self.db.add(contact)
            await self.db.flush()
            identity.contact_id = contact.id
            self.db.add(identity)
            await self.db.flush()
            await record_audit(
                self.db,
                action="resolve_contact_channel_identity",
                actor_id=actor_id,
                target_type="contact",
                target_id=str(contact.id),
                payload={
                    "identity_id": str(identity.id),
                    "provider": provider,
                    "account_key": account_key,
                },
            )
            await savepoint.commit()
            return identity
        except IntegrityError:
            await savepoint.rollback()
            winner = await self.db.scalar(
                select(ContactChannelIdentity).where(
                    ContactChannelIdentity.provider == provider,
                    ContactChannelIdentity.account_key == account_key,
                    ContactChannelIdentity.external_id == external_id,
                )
            )
            if winner is None:
                raise
            return winner

    async def adopt_conversation(
        self,
        conversation: Conversation,
        *,
        account_key: str,
        actor_id: uuid.UUID | None = None,
    ) -> ContactChannelIdentity:
        account_key = account_key.strip()
        if not account_key or len(account_key) > 128 or account_key.startswith("legacy:"):
            raise ValueError("a validated configured channel account key is required")
        external_id = (
            conversation.zalo_chat_id[3:]
            if conversation.zalo_channel == "oa" and conversation.zalo_chat_id.startswith("oa:")
            else conversation.zalo_chat_id
        )
        identity = await self.resolve_channel_identity(
            provider="zalo",
            account_key=account_key,
            external_id=external_id,
            actor_id=actor_id,
        )
        if conversation.contact_id is None:
            conversation.contact_id = identity.contact_id
            conversation.channel_identity_id = identity.id
        elif conversation.contact_id != identity.contact_id:
            raise ConflictError("conversation is linked to a different contact")
        elif conversation.channel_identity_id not in (None, identity.id):
            raise ConflictError("conversation is linked to a different channel identity")
        else:
            conversation.channel_identity_id = identity.id
        await self.db.flush()
        await record_audit(
            self.db,
            action="adopt_conversation_contact",
            actor_id=actor_id,
            target_type="conversation",
            target_id=str(conversation.id),
            payload={
                "contact_id": str(identity.contact_id),
                "channel_identity_id": str(identity.id),
            },
        )
        return identity
