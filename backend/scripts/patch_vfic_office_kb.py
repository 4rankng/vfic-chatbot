#!/usr/bin/env python3
"""One-off: ground VFIC office/company facts into the lg-display KB.

Patches the ACTIVE contacts + faq category revisions (adds the real VFIC office
address, hotline, legal name, and an explicit company-vs-factory FAQ), creates
new validated revisions through the same service path the backfill script uses,
embeds, activates, and bumps KB caches. Facts sourced from vficmanpower.com
(operator-confirmed).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys

from sqlalchemy import select

from app.core.cache import bump_kb_caches
from app.core.db import async_session
from app.models.company import Project
from app.models.knowledge import (
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
)
from app.models.user import Role, User
from app.services.audit_service import record_audit
from app.services.integration_settings import IntegrationSettingsService
from app.services.knowledge.category_contracts import CATEGORY_DOCUMENT_MODELS, category_checksum
from app.services.knowledge.category_markdown import build_source_markdown
from app.services.knowledge.category_service import KnowledgeCategoryService

PROJECT_SLUG = "lg-display"
SOURCE_FILENAME = "manual-vfic-office-address-20260928"

OFFICE_ADDRESS = "Manhattan 07-08, Vinhomes Imperia, phường Hồng Bàng, TP. Hải Phòng"
HOTLINE = "18007228"
LEGAL_NAME = "Công ty Cổ phần Quốc tế Thương mại và Dịch vụ Việt Pháp"
TAX_CODE = "0201307104"

FAQ_QUESTION = "Địa chỉ công ty Việt Pháp (VFIC) ở đâu?"
FAQ_ANSWER = (
    f"{LEGAL_NAME} (thương hiệu Nhân lực VFIC) có văn phòng tại {OFFICE_ADDRESS}. "
    f"Hotline miễn phí: 1800 7228. Lưu ý: đây là văn phòng công ty, KHÁC với nơi làm "
    "việc của các vị trí tuyển dụng — ví dụ công nhân LG Display làm việc tại nhà máy "
    "LG Display, KCN Tràng Duệ, An Dương, Hải Phòng (có xe đưa đón từ các điểm trong "
    "thành phố)."
)
FAQ_VARIANTS = [
    "viet phap dia chi cty o dau",
    "dia chi vfic o dau",
    "vfic o dau",
    "cong ty viet phap o dau",
    "van phong vfic o dau",
    "cty o dau vay",
    "địa chỉ vfic",
    "địa chỉ công ty việt pháp",
]


def _faq_id(question: str) -> str:
    digest = hashlib.sha256(question.strip().lower().encode("utf-8")).hexdigest()[:16]
    return f"faq-{digest}"


def _source_markdown(payload: dict) -> str:
    return build_source_markdown(payload)


async def _patch_category(
    db,
    service: KnowledgeCategoryService,
    embedder,
    admin_id,
    project_id: str,
    category_key: str,
    patch,
) -> None:
    category = await db.scalar(
        select(KnowledgeCategory).where(
            KnowledgeCategory.project_id == project_id,
            KnowledgeCategory.category_key == category_key,
        )
    )
    if category is None or category.active_revision_id is None:
        raise RuntimeError(f"no active revision for category {category_key}")
    active = await db.get(KnowledgeCategoryRevision, category.active_revision_id)
    payload = json.loads(json.dumps(active.normalized_payload))  # deep copy
    patch(payload)

    model = CATEGORY_DOCUMENT_MODELS[_key_enum(category_key)]
    document = model.model_validate(payload)
    latest = await db.scalar(
        select(func_max_revision()).where(KnowledgeCategoryRevision.category_id == category.id)
    )
    revision = KnowledgeCategoryRevision(
        category_id=category.id,
        revision_no=int(latest or 0) + 1,
        status=KnowledgeCategoryRevisionStatus.STAGED,
        source_filename=SOURCE_FILENAME,
        source_yaml=_source_markdown(document.model_dump(mode="json", exclude_none=True)),
        normalized_payload=document.model_dump(mode="json"),
        content_sha256=category_checksum(document),
        created_by=admin_id,
    )
    db.add(revision)
    await db.flush()
    await record_audit(
        db,
        action="patch_vfic_office_kb",
        actor_id=admin_id,
        target_type="knowledge_category_revision",
        target_id=str(revision.id),
        payload={"project_id": project_id, "category": category_key},
    )
    await db.commit()
    await service.activate_revision(revision.id, embedder, start_category_authority=False)
    print(f"patched+activated {category_key} rev {revision.revision_no}")


def _key_enum(category_key: str):
    from app.schemas.knowledge_categories import KnowledgeCategoryKey

    return KnowledgeCategoryKey(category_key)


def func_max_revision():
    from sqlalchemy import func

    return func.max(KnowledgeCategoryRevision.revision_no)


def _patch_contacts(payload: dict) -> None:
    rows = payload["contacts"]
    for row in rows:
        if row["id"] == "legacy-vfic-support":
            row["phone"] = HOTLINE
            row["address"] = OFFICE_ADDRESS
            extra = (
                f"{LEGAL_NAME} (VFIC), MST {TAX_CODE}. Văn phòng công ty tại {OFFICE_ADDRESS}; "
                "nơi làm việc của vị trí tuyển dụng (ví dụ LG Display) tại nhà máy KCN "
                "Tràng Duệ, An Dương, Hải Phòng."
            )
            notes = (row.get("notes") or "").strip()
            row["notes"] = f"{notes}\n{extra}" if notes else extra
            return
    raise RuntimeError("legacy-vfic-support contact row not found")


def _patch_faq(payload: dict) -> None:
    rows = payload["faq"]
    if any(row["id"] == _faq_id(FAQ_QUESTION) for row in rows):
        raise RuntimeError("faq row already present")
    rows.append(
        {
            "id": _faq_id(FAQ_QUESTION),
            "question": FAQ_QUESTION,
            "answer": FAQ_ANSWER,
            "tags": [],
            "question_variants": FAQ_VARIANTS,
            "required_terms": [],
            "forbidden_terms": [],
        }
    )


async def main() -> int:

    async with async_session() as db:
        project = await db.scalar(select(Project).where(Project.slug == PROJECT_SLUG))
        if project is None:
            print(f"project not found: {PROJECT_SLUG}", file=sys.stderr)
            return 2
        admin = await db.scalar(
            select(User)
            .where(User.role == Role.admin, User.disabled.is_(False))
            .order_by(User.created_at, User.id)
            .limit(1)
        )
        if admin is None:
            print("no active admin", file=sys.stderr)
            return 2
        openrouter = await IntegrationSettingsService(db).resolve_openrouter()
        from app.graph.clients import build_embedder

        embedder = build_embedder(openrouter_api_key=openrouter.api_key)
        service = KnowledgeCategoryService(db)
        await _patch_category(
            db, service, embedder, admin.id, str(project.id), "contacts", _patch_contacts
        )
        await _patch_category(
            db, service, embedder, admin.id, str(project.id), "faq", _patch_faq
        )
        await bump_kb_caches()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
