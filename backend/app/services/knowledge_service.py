"""Knowledge ingest + publishing (port of VFIC Knowledge Ingest + LLM training pipeline).

Two ingest paths:
  * ``process(embedder, doc, llm_json=None)`` — mechanical 1-chunk fallback (legacy,
    tests). When ``llm_json`` is supplied it runs the full LLM
    ``KnowledgePipeline`` (digest -> embed -> index).
  * ``upload_bytes(...)`` — multipart upload: extract text from the source file,
    persist the original to a volume, create the doc (stage=UPLOADED); the caller
    then enqueues the async ingest job for the real LLM pipeline.

Successful ingest publishes bot-usable knowledge immediately. Admins remove bad
sources by archiving/replacing them rather than approving a review queue.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import uuid
from typing import Any, Awaitable, Callable
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector import vec_literal
from app.models.company import Project
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.models.user import User
from app.schemas.knowledge import KnowledgeDocumentUpdate
from app.services.audit_service import record_audit
from app.services.knowledge import LLMJson
from app.services.knowledge.canonical import (
    SCHEMA_VERSION,
    checksum_text,
    parse_canonical_markdown,
    repair_canonical_markdown,
)
from app.services.knowledge.repository import KnowledgeChunkRepo, rebuild_bus_timetable
from app.services.storage import persist_original_upload

Embedder = Callable[[str], Awaitable[list[float]]]

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
WORD_XML_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class KnowledgeFileExtractionError(ValueError):
    """Raised when an uploaded source file cannot be converted to ingestable text."""


def _detect_upload_format(file_name: str, content_type: str) -> str:
    suffix = Path(file_name or "").suffix.lower()
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if suffix == ".docx" or normalized_type == DOCX_MIME_TYPE:
        return "docx"
    if suffix == ".md" or normalized_type in {"text/markdown", "text/x-markdown"}:
        return "markdown"
    if suffix == ".txt" or normalized_type.startswith("text/"):
        return "text"
    return suffix.removeprefix(".") or normalized_type or "binary"


def _extract_docx_text(data: bytes) -> str:
    """Extract paragraph text from a Word DOCX without adding runtime dependencies."""
    try:
        with ZipFile(BytesIO(data)) as archive:
            document_xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError) as exc:
        raise KnowledgeFileExtractionError("DOCX không hợp lệ hoặc thiếu nội dung Word.") from exc

    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError as exc:
        raise KnowledgeFileExtractionError("Không đọc được nội dung XML trong DOCX.") from exc

    paragraphs: list[str] = []
    for paragraph in root.iter(f"{WORD_XML_NS}p"):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{WORD_XML_NS}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{WORD_XML_NS}tab":
                parts.append("\t")
            elif node.tag in {f"{WORD_XML_NS}br", f"{WORD_XML_NS}cr"}:
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs)


class KnowledgeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, doc_id: uuid.UUID) -> KnowledgeDocument | None:
        return await self.db.get(KnowledgeDocument, doc_id)

    async def list_chunks(self, doc_id: uuid.UUID, *, limit: int = 50) -> list[dict]:
        return await KnowledgeChunkRepo(self.db).list_for_doc(doc_id, limit=limit)

    async def upload(self, file_name: str, content: str, drive_file_id: str | None = None, project_id: uuid.UUID | None = None) -> KnowledgeDocument:
        doc = KnowledgeDocument(
            file_name=file_name,
            drive_file_id=drive_file_id,
            raw_text=content,
            project_id=project_id,
            status=KnowledgeStatus.UPLOADED,
            stage="UPLOADED",
            source="google_drive" if drive_file_id else "upload",
        )
        self.db.add(doc)
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def upload_bytes(
        self,
        file_name: str,
        content_type: str,
        data: bytes,
        *,
        project_id: uuid.UUID | None = None,
        require_canonical: bool = False,
    ) -> KnowledgeDocument:
        """Multipart upload: extract text, persist the original, create doc."""
        extracted_text, source_metadata = self._extract_upload_text(file_name, content_type, data)
        enforce_canonical = require_canonical and source_metadata["format"] != "docx"
        raw_text, repair = self._repair_if_canonical(extracted_text, enforce_canonical)
        canonical = parse_canonical_markdown(raw_text) if enforce_canonical else None
        if canonical is not None and project_id is None:
            project_id = await self._resolve_project_from_canonical(canonical)
        metadata, version = self._build_canonical_metadata(canonical, raw_text, extracted_text, repair)
        metadata["source_file"] = source_metadata
        storage_path = persist_original_upload(file_name, data)
        doc = KnowledgeDocument(
            file_name=file_name,
            source="upload",
            version=version,
            mime_type=content_type or None,
            storage_path=storage_path,
            raw_text=raw_text,
            metadata_=metadata,
            project_id=project_id,
            status=KnowledgeStatus.UPLOADED,
            stage="EXTRACTED" if raw_text.strip() else "UPLOADED",
        )
        self.db.add(doc)
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    @staticmethod
    def _extract_upload_text(file_name: str, content_type: str, data: bytes) -> tuple[str, dict]:
        """Return ingestable text plus source-file metadata for an upload."""
        file_format = _detect_upload_format(file_name, content_type)
        if file_format == "docx":
            text = _extract_docx_text(data)
            if not text.strip():
                raise KnowledgeFileExtractionError("DOCX không có văn bản để ingest.")
            return text, {
                "format": "docx",
                "mime_type": content_type or DOCX_MIME_TYPE,
                "extraction": "word_ooxml",
                "text_checksum": checksum_text(text),
            }
        text_value = data.decode("utf-8", errors="replace")
        return text_value, {
            "format": file_format,
            "mime_type": content_type or None,
            "extraction": "utf8_decode",
            "text_checksum": checksum_text(text_value),
        }

    @staticmethod
    def _repair_if_canonical(text: str, require_canonical: bool) -> tuple[str, Any]:
        """Apply canonical markdown repair if requested. Returns (repaired_text, repair_result)."""
        if not require_canonical:
            return text, None
        repair = repair_canonical_markdown(text)
        return repair.text, repair

    async def _resolve_project_from_canonical(self, canonical: Any) -> uuid.UUID | None:
        """Look up a project by slug from the canonical document metadata."""
        slug = str(canonical.metadata.get("project_slug") or "").strip()
        if not slug:
            return None
        project = (
            await self.db.scalars(
                select(Project).where(func.lower(Project.slug) == slug.lower()).limit(1)
            )
        ).first()
        return project.id if project else None

    @staticmethod
    def _build_canonical_metadata(canonical: Any, raw_text: str, original_text: str, repair: Any) -> tuple[dict, str | None]:
        """Assemble the metadata dict and version for a canonical document."""
        if canonical is None:
            return {}, None
        version = str(canonical.metadata.get("doc_version") or "")
        canonical_meta: dict = {
            "document": canonical.metadata,
            "validation": {
                "chunk_count": len(canonical.chunks),
                "bus_route_count": len(canonical.bus_timetable.routes),
                "bus_stop_count": sum(len(route.stops) for route in canonical.bus_timetable.routes),
            },
        }
        if repair is not None and repair.changed:
            canonical_meta["repair"] = {
                "applied": True,
                "count": len(repair.repairs),
                "fixes": repair.repairs,
                "original_checksum": checksum_text(original_text),
            }
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "checksum": checksum_text(raw_text),
            "canonical": canonical_meta,
        }
        return metadata, version

    async def process(self, embedder: Embedder, doc: KnowledgeDocument, *, llm_json: LLMJson | None = None) -> KnowledgeDocument:
        """Run the ingest pipeline.

        With ``llm_json`` -> full LLM ``KnowledgePipeline`` (digest/embed/index).
        Without -> mechanical 1-chunk fallback (legacy/tests).
        """
        if llm_json is not None:
            from app.services.knowledge import KnowledgePipeline

            await KnowledgePipeline(self.db, embedder, llm_json).run(doc)
            await self.db.refresh(doc)
            return doc

        # --- mechanical fallback: embed 1 chunk-per-doc (whole content) ---
        doc.status = KnowledgeStatus.PROCESSING
        doc.stage = "PROCESSING"
        content = doc.raw_text or ""
        emb = vec_literal(await embedder(content))
        await KnowledgeChunkRepo(self.db).replace_with_single_chunk(doc, content, emb)
        doc.status = KnowledgeStatus.PUBLISHED
        doc.stage = "PUBLISHED"
        await self.db.commit()
        # rebuild the structured bus graph from the `documents` VIEW (best-effort;
        # never block ingest). The repo helper owns the SQL + commit.
        try:
            await rebuild_bus_timetable(self.db)
        except Exception:  # noqa: BLE001
            pass
        await self.db.refresh(doc)
        return doc

    async def archive(self, doc: KnowledgeDocument, *, actor: User) -> KnowledgeDocument:
        doc.status = KnowledgeStatus.ARCHIVED
        await record_audit(self.db, action="archive_knowledge", actor_id=actor.id, target_type="knowledge_document", target_id=str(doc.id))
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def update(self, doc: KnowledgeDocument, body: KnowledgeDocumentUpdate, *, actor: User) -> KnowledgeDocument:
        if body.file_name is not None:
            doc.file_name = body.file_name.strip()
        if "project_id" in body.model_fields_set:
            if body.project_id is not None and await self.db.get(Project, body.project_id) is None:
                from fastapi import HTTPException, status

                raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
            doc.project_id = body.project_id
            await self.db.execute(
                text("UPDATE knowledge_chunks SET project_id = :pid WHERE document_id = :did"),
                {
                    "pid": str(body.project_id) if body.project_id is not None else None,
                    "did": str(doc.id),
                },
            )
        await record_audit(self.db, action="update_knowledge", actor_id=actor.id, target_type="knowledge_document", target_id=str(doc.id))
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def delete(self, doc: KnowledgeDocument, *, actor: User) -> None:
        target_id = str(doc.id)
        await record_audit(self.db, action="delete_knowledge", actor_id=actor.id, target_type="knowledge_document", target_id=target_id)
        await self.db.delete(doc)
        await self.db.commit()

    async def reindex(self, embedder: Embedder, doc: KnowledgeDocument, *, llm_json: LLMJson | None = None) -> KnowledgeDocument:
        return await self.process(embedder, doc, llm_json=llm_json)

    async def search_test(self, embedder: Embedder, query: str, top_k: int = 10, *, project_id: uuid.UUID | None = None) -> list[dict]:
        emb = vec_literal(await embedder(query))
        return await KnowledgeChunkRepo(self.db).search_similar(emb, top_k, project_id=project_id)

    async def list(self, *, status_: KnowledgeStatus | None = None, project_id: uuid.UUID | None = None) -> list[KnowledgeDocument]:
        q = select(KnowledgeDocument)
        if status_ is not None:
            q = q.where(KnowledgeDocument.status == status_)
        if project_id is not None:
            q = q.where(KnowledgeDocument.project_id == project_id)
        return list((await self.db.scalars(q.order_by(desc(KnowledgeDocument.created_at)))).all())

    async def reconcile(self, current_drive_ids: list[str]) -> int:
        """Drop knowledge_documents whose drive_file_id is no longer in Drive (cascades chunks)."""
        res = await self.db.execute(
            text(
                "DELETE FROM knowledge_documents WHERE drive_file_id IS NOT NULL "
                "AND drive_file_id <> ALL(CAST(:ids AS text[]))"
            ),
            {"ids": current_drive_ids},
        )
        await self.db.commit()
        return res.rowcount or 0
