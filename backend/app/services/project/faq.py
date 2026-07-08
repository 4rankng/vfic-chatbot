"""Managed project FAQ CRUD sub-service.

Extracted from :class:`ProjectService`: create / update / delete / list of
admin-managed FAQ pairs, including the embedding write and the maintenance of the
managed FAQ document's raw text. The parent service composes this via a thin
delegate so the public ``ProjectService`` surface is unchanged.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_cache_version
from app.core.vector import vec_literal
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.user import User
from app.schemas.projects import (
    ProjectFaqCreate,
    ProjectFaqOut,
    ProjectFaqResponse,
    ProjectFaqUpdate,
)
from app.services.audit_service import record_audit
from app.services.errors import NotFoundError
from app.services.knowledge.text_ingestion import (
    estimate_token_count,
    hash_text,
    line_range_for_quote,
    make_content_plain,
)
from app.services.project.mapping import _faq_answer_from_content
from app.services.project.repository import ProjectRepository, require_project


class ProjectFaqService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ProjectRepository(self.db)

    async def list_faq(self, project_id: uuid.UUID, *, limit: int = 12) -> ProjectFaqResponse:
        """List published FAQ chunks for a project."""
        await require_project(self.db, project_id)
        limit = min(50, max(1, limit))
        rows = await self.repo.list_faq_chunks(project_id, limit=limit)
        data = [
            ProjectFaqOut(
                id=row["id"],
                question=(row["questions"] or ["FAQ"])[0],
                answer=_faq_answer_from_content(row["content"], (row["questions"] or ["FAQ"])[0]),
                source_name=row["file_name"],
                source_anchor=row["source_anchor"],
            )
            for row in rows
        ]
        return ProjectFaqResponse(data=data, total=len(data))

    async def create_faq(
        self, project_id: uuid.UUID, body: ProjectFaqCreate, actor: User
    ) -> ProjectFaqOut:
        """Create one managed FAQ question/answer pair for a project."""
        project = await require_project(self.db, project_id)
        question = self._clean_faq_text(body.question)
        answer = self._clean_faq_text(body.answer)
        document = await self.repo.managed_faq_document(project)
        chunk_index = await self.repo.next_faq_chunk_index(document.id)
        content = self._faq_content(question, answer)
        chunk = KnowledgeChunk(
            document_id=document.id,
            chunk_index=chunk_index,
            content=content,
            metadata_={
                "source_anchor": f"FAQ: {question}",
                "document_metadata": document.metadata_ or {},
            },
            project_id=project_id,
            source_quote=answer,
            summary=answer[:500],
            questions=[question],
            category="faq",
            entities={"project": project.slug},
            confidence="high",
            search_text=f"{question}\n{answer}",
        )
        self.db.add(chunk)
        document.raw_text = self._append_raw_faq(document.raw_text, question, answer)
        await self.db.flush()
        text_file = await self.repo.ensure_active_faq_file(project, document)
        line_start, line_end = line_range_for_quote(document.raw_text or "", answer)
        chunk.kb_version_id = text_file.kb_version_id
        chunk.file_id = text_file.id
        chunk.chunk_type = "faq"
        chunk.section_path = [document.file_name, f"FAQ: {question}"]
        chunk.line_start = line_start
        chunk.line_end = line_end
        chunk.content_plain = make_content_plain(question, answer)
        chunk.token_count = estimate_token_count(chunk.content)
        chunk.chunk_sha256 = hash_text(chunk.content)
        await self._embed_faq_chunk(chunk.id, question, answer)
        await record_audit(
            self.db,
            action="create_project_faq",
            actor_id=actor.id,
            target_type="knowledge_chunk",
            target_id=str(chunk.id),
        )
        await self.db.commit()
        await bump_cache_version("knowledge")
        await self.db.refresh(chunk)
        return self._faq_out(
            {
                "id": chunk.id,
                "content": chunk.content,
                "questions": chunk.questions,
                "source_anchor": chunk.metadata_.get("source_anchor"),
                "file_name": document.file_name,
            }
        )

    async def update_faq(
        self, project_id: uuid.UUID, chunk_id: uuid.UUID, body: ProjectFaqUpdate, actor: User
    ) -> ProjectFaqOut:
        """Edit one published FAQ question/answer pair."""
        await require_project(self.db, project_id)
        row = await self.repo.get_faq_chunk(project_id, chunk_id)
        if not row:
            raise NotFoundError("faq not found")
        current_question = (row["questions"] or ["FAQ"])[0]
        current_answer = _faq_answer_from_content(row["content"], current_question)
        question = self._clean_faq_text(body.question or current_question)
        answer = self._clean_faq_text(body.answer or current_answer)
        chunk = await self.db.get(KnowledgeChunk, chunk_id)
        if not chunk:
            raise NotFoundError("faq not found")
        chunk.content = self._faq_content(question, answer)
        chunk.questions = [question]
        chunk.source_quote = answer
        chunk.summary = answer[:500]
        chunk.metadata_ = {
            **(chunk.metadata_ or {}),
            "source_anchor": f"FAQ: {question}",
        }
        chunk.search_text = f"{question}\n{answer}"
        document = await self.db.get(KnowledgeDocument, chunk.document_id)
        if document is not None:
            document.raw_text = self._replace_raw_faq(
                document.raw_text, current_question, current_answer, question, answer
            )
            project = await require_project(self.db, project_id)
            text_file = await self.repo.ensure_active_faq_file(project, document)
            line_start, line_end = line_range_for_quote(document.raw_text or "", answer)
            chunk.kb_version_id = text_file.kb_version_id
            chunk.file_id = text_file.id
            chunk.line_start = line_start
            chunk.line_end = line_end
        chunk.section_path = [row["file_name"], f"FAQ: {question}"]
        chunk.chunk_type = "faq"
        chunk.content_plain = make_content_plain(question, answer)
        chunk.token_count = estimate_token_count(chunk.content)
        chunk.chunk_sha256 = hash_text(chunk.content)
        await self._embed_faq_chunk(chunk.id, question, answer)
        await record_audit(
            self.db,
            action="update_project_faq",
            actor_id=actor.id,
            target_type="knowledge_chunk",
            target_id=str(chunk_id),
        )
        await self.db.commit()
        await bump_cache_version("knowledge")
        await self.db.refresh(chunk)
        return self._faq_out(
            {
                "id": chunk.id,
                "content": chunk.content,
                "questions": chunk.questions,
                "source_anchor": chunk.metadata_.get("source_anchor"),
                "file_name": row["file_name"],
            }
        )

    async def delete_faq(self, project_id: uuid.UUID, chunk_id: uuid.UUID, actor: User) -> None:
        """Delete one FAQ pair from the project's published knowledge chunks."""
        await require_project(self.db, project_id)
        row = await self.repo.get_faq_chunk(project_id, chunk_id)
        if not row:
            raise NotFoundError("faq not found")
        await self.repo.delete_faq_chunk(chunk_id)
        await record_audit(
            self.db,
            action="delete_project_faq",
            actor_id=actor.id,
            target_type="knowledge_chunk",
            target_id=str(chunk_id),
        )
        await self.db.commit()
        await bump_cache_version("knowledge")

    async def _embed_faq_chunk(self, chunk_id: uuid.UUID, question: str, answer: str) -> None:
        from app.graph.clients import build_embedder
        from app.services.integration_settings import IntegrationSettingsService

        openrouter_config = await IntegrationSettingsService(self.db).resolve_openrouter()
        vector = await build_embedder(openrouter_api_key=openrouter_config.api_key)(
            f"{question}\n{answer}"
        )
        await self.repo.set_chunk_embedding(chunk_id, vec_literal(vector))

    @staticmethod
    def _clean_faq_text(value: str) -> str:
        return " ".join((value or "").strip().split()) if "\n" not in value else value.strip()

    @staticmethod
    def _faq_content(question: str, answer: str) -> str:
        return f"FAQ: {question}\n{answer}"

    @staticmethod
    def _append_raw_faq(raw_text: str | None, question: str, answer: str) -> str:
        block = f"\n\n### FAQ: {question}\n\nQuestion: {question}\n\nAnswer: {answer}\n"
        return f"{(raw_text or '').rstrip()}{block}".strip()

    @staticmethod
    def _replace_raw_faq(
        raw_text: str | None,
        current_question: str,
        current_answer: str,
        question: str,
        answer: str,
    ) -> str:
        old_block = f"### FAQ: {current_question}\n\nQuestion: {current_question}\n\nAnswer: {current_answer}"
        new_block = f"### FAQ: {question}\n\nQuestion: {question}\n\nAnswer: {answer}"
        raw = raw_text or ""
        if old_block in raw:
            return raw.replace(old_block, new_block, 1)
        return ProjectFaqService._append_raw_faq(raw, question, answer)

    @staticmethod
    def _faq_out(row: dict) -> ProjectFaqOut:
        question = (row["questions"] or ["FAQ"])[0]
        return ProjectFaqOut(
            id=row["id"],
            question=question,
            answer=_faq_answer_from_content(row["content"], question),
            source_name=row["file_name"],
            source_anchor=row["source_anchor"],
        )
