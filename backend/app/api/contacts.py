"""Dormant authenticated generic Contact API."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, require_capability
from app.core.db import get_db
from app.models.contact import Contact
from app.models.user import Role, User
from app.schemas.contacts import (
    ChannelIdentityCreate,
    ChannelIdentityOut,
    ChannelIdentitySummaryOut,
    ContactCreate,
    ContactListResponse,
    ContactOut,
    ContactUpdate,
)
from app.services.contact_service import ContactService
from app.services.errors import ForbiddenError

router = APIRouter(
    prefix="/contacts",
    tags=["contacts"],
    dependencies=[Depends(require_capability("conversation"))],
)


async def _out(service: ContactService, contact: Contact) -> ContactOut:
    identities = contact.__dict__.get("channel_identities")
    if identities is None:
        identities = await service.identities(contact.id)
    return ContactOut(
        id=contact.id,
        display_name=contact.display_name,
        primary_email=contact.primary_email,
        primary_phone=contact.primary_phone,
        avatar_url=contact.avatar_url,
        locale=contact.locale,
        version=contact.version,
        created_at=contact.created_at,
        updated_at=contact.updated_at,
        primary_channel=ChannelIdentitySummaryOut.model_validate(identities[0])
        if identities
        else None,
        channel_identities=[ChannelIdentityOut.model_validate(item) for item in identities],
    )


@router.get("", response_model=ContactListResponse)
async def list_contacts(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    q: str | None = Query(None, max_length=200),
    provider: str | None = Query(None, max_length=32),
    account_key: str | None = Query(None, max_length=128),
    external_id: str | None = Query(None, max_length=256),
    sort: str | None = Query(None, pattern="^(created_at|updated_at|display_name)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContactListResponse:
    service = ContactService(db)
    rows, total = await service.list(
        viewer=user,
        page=page,
        per_page=per_page,
        q=q,
        provider=provider,
        account_key=account_key,
        external_id=external_id,
        sort_by=sort,
        order=order,
    )
    return ContactListResponse(data=[await _out(service, row) for row in rows], total=total)


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def create_contact(
    body: ContactCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ContactOut:
    if user.role != Role.admin:
        raise ForbiddenError("admin only")
    service = ContactService(db)
    return await _out(service, await service.create(body, user))


@router.get("/{contact_id}", response_model=ContactOut)
async def get_contact(
    contact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContactOut:
    service = ContactService(db)
    return await _out(service, await service.get_visible(contact_id, user))


@router.patch("/{contact_id}", response_model=ContactOut)
async def update_contact(
    contact_id: uuid.UUID,
    body: ContactUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContactOut:
    service = ContactService(db)
    contact = await service.get_visible(contact_id, user)
    return await _out(service, await service.update(contact, body, user))


@router.post(
    "/{contact_id}/channel-identities",
    response_model=ChannelIdentityOut,
    status_code=status.HTTP_201_CREATED,
)
async def attach_channel_identity(
    contact_id: uuid.UUID,
    body: ChannelIdentityCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChannelIdentityOut:
    if user.role != Role.admin:
        raise ForbiddenError("admin only")
    service = ContactService(db)
    contact = await service.get_visible(contact_id, user)
    return ChannelIdentityOut.model_validate(await service.attach_identity(contact, body, user))
