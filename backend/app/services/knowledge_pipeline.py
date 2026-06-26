"""LLM-driven "training pipeline" — turns a raw KB file into RAG-efficient units.

This is the data-transformation pipeline the user asked for. It is LLM-driven (the
heart of it), not just mechanical chunking. For one document it runs:

  extract  -> raw text (handled at upload; here we assume ``doc.raw_text`` is set)
  digest   -> the LLM cleans, semantic-splits, self-contained-rewrites, extracts
              metadata + retrieval questions, and flags faithfulness for each unit
  embed    -> GeminiEmbedder.batch over the digested units
  index    -> regenerate the project's catalog card (the agent's master-index entry)

The LLM step is injected (``llm_json``) so the pipeline is unit-testable without API
keys; a fake returns canned JSON. ``KnowledgeService.process(embedder, doc)`` keeps a
mechanical 1-chunk fallback when no ``llm_json`` is supplied (legacy/tests).

STRICT grounding rule (existing persona contract): every unit carries a verbatim
``source_quote``; low-confidence / inferred units are flagged, never silently invented.
"""
from __future__ import annotations

import io
import json
import logging
import uuid
from typing import Any, Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.vector import vec_literal

logger = logging.getLogger(__name__)

# A function (system_prompt, user_text) -> raw JSON text. Injected so this module
# stays free of langchain/google imports and is unit-testable with a fake.
LLMJson = Callable[[str, str], Awaitable[str]]
Embedder = Callable[[str], Awaitable[list[float]]]

CATEGORIES = ("job", "salary", "schedule", "policy", "faq", "contact", "benefits", "other")
_CONFIDENCE = ("high", "medium", "low")

DIGEST_SYSTEM_PROMPT = """Bạn là bộ phân tích tài liệu cho chatbot tuyển dụng VFIC. \
Bạn nhận một đoạn tài liệu thô (tiếng Việt) và phải biến nó thành các đơn vị kiến thức \
tối ưu cho tìm kiếm ngữ nghĩa (RAG).

YÊU CẦU với từng đơn vị (unit):
1. Làm sạch: bỏ header/footer/lặp lại/số trang/lời phủ nhận.
2. Tách ngữ nghĩa: mỗi unit = MỘT sự thật/hướng dẫn độc lập, không phụ thuộc ngữ cảnh xung quanh.
3. Viết lại tự chứa: thêm ngữ cảnh cần thiết để unit đứng một mình vẫn hiểu được \
(ví dụ "LG Display Hải Phòng — tuyển operator ca đêm, lương 9-11 triệu" thay vì chỉ "lương 9-11 triệu").
4. Trích metadata: category (một trong: job|salary|schedule|policy|faq|contact|benefits|other), \
entities {job_title, salary_range, location, shift,...} nếu có.
5. Sinh câu hỏi: 1-3 câu hỏi mà unit này trả lời được (giúp tăng recall).
6. Trung thực: source_quote = nguyên văn câu/khoản tương ứng trong tài liệu gốc. \
confidence = high/medium/low; is_inference=true nếu là suy luận chứ không phải kể trực tiếp. \
TUYỆT ĐỐI không bịa ra thông tin không có trong tài liệu.

Trả về ĐÚNG MỘT JSON object theo schema sau, không kèm markdown/code fence:
{
  "document_summary": "tóm tắt 2-4 câu về tài liệu",
  "units": [
    {
      "content": "câu tự chứa (tiếng Việt)",
      "source_quote": "nguyên văn từ tài liệu gốc",
      "summary": "tóm tắt ≤1 câu",
      "questions": ["câu hỏi 1?", "câu hỏi 2?"],
      "category": "job|salary|schedule|policy|faq|contact|benefits|other",
      "entities": {"job_title": "...", "salary_range": "...", "location": "...", "shift": "..."},
      "source_anchor": "tr.3 / §Lương",
      "confidence": "high|medium|low",
      "is_inference": false
    }
  ]
}
Nếu tài liệu không có nội dung hữu ích, trả về {"document_summary": "", "units": []}."""

INDEX_SYSTEM_PROMPT = """Bạn là trợ lý tổng hợp danh mục dự án cho chatbot tuyển dụng VFIC. \
Dựa vào các đơn vị kiến thức (tiếng Việt) của một dự án/sản phẩm, sinh ra một "thẻ danh mục" \
ngắn gọn để agent giới thiệu sản phẩm đó cho ứng viên.

Trả về ĐÚNG MỘT JSON object, không kèm markdown:
{
  "summary": "mô tả 1-2 câu về dự án/nhà máy",
  "key_roles": ["vị trí tuyển chính", "..."],
  "location": "địa điểm",
  "highlights": ["điểm nổi bật", "..."]
}
Chỉ dựa vào dữ liệu cung cấp, không bịa."""


# --------------------------------------------------------------------------- extract
def extract_text(file_name: str, content_type: str, data: bytes) -> str:
    """Parse Office/text file bytes to plain UTF-8 text (Vietnamese-safe)."""
    name = (file_name or "").lower()
    ct = (content_type or "").lower()
    blob = name.endswith

    def _dec() -> str:
        return data.decode("utf-8", errors="replace")

    if "pdf" in ct or blob(".pdf"):
        return _extract_pdf(data)
    if "officedocument.wordprocessingml" in ct or blob(".docx"):
        return _extract_docx(data)
    if "spreadsheet" in ct or blob(".xlsx"):
        return _extract_xlsx(data)
    if blob(".csv") or "csv" in ct:
        return _dec()
    return _dec()  # .txt / .md / unknown -> treat as text


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    parts: list[str] = []
    for page in PdfReader(io.BytesIO(data)).pages:
        t = (page.extract_text() or "").strip()
        if t:
            parts.append(t)
    return "\n\n".join(parts)


def _extract_docx(data: bytes) -> str:
    import docx

    doc = docx.Document(io.BytesIO(data))
    parts: list[str] = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    for tbl in doc.tables:
        for row in tbl.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_xlsx(data: bytes) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts: list[str] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            if any(c.strip() for c in cells):
                parts.append("\t".join(cells))
    wb.close()
    return "\n".join(parts)


def split_for_digest(text: str, max_chars: int | None = None) -> list[str]:
    """Naively split long text into LLM-sized sections with small overlap.

    The LLM does the real semantic splitting per section; this just keeps each call
    within a sane input size. Paragraph boundaries are respected where possible.
    """
    max_chars = max_chars or get_settings().digest_section_chars
    text = (text or "").strip()
    if len(text) <= max_chars:
        return [text] if text else []
    step = max(1, max_chars - 400)  # 400-char overlap
    sections: list[str] = []
    for start in range(0, len(text), step):
        chunk = text[start : start + max_chars]
        if chunk.strip():
            sections.append(chunk)
        if start + max_chars >= len(text):
            break
        if len(sections) >= get_settings().digest_max_sections:
            break
    return sections


# --------------------------------------------------------------------------- digest
class DigestError(Exception):
    """Raised when the LLM output cannot be coerced into the unit schema."""


def _coerce_unit(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise DigestError(f"unit is not an object: {type(raw).__name__}")
    content = (raw.get("content") or "").strip()
    if not content:
        raise DigestError("unit missing non-empty 'content'")
    cat = str(raw.get("category") or "other").strip().lower()
    if cat not in CATEGORIES:
        cat = "other"
    conf = str(raw.get("confidence") or "medium").strip().lower()
    if conf not in _CONFIDENCE:
        conf = "medium"
    questions = raw.get("questions") or []
    if not isinstance(questions, list):
        questions = [str(questions)]
    questions = [str(q).strip() for q in questions if str(q).strip()]
    entities = raw.get("entities") or {}
    if not isinstance(entities, dict):
        entities = {}
    return {
        "content": content,
        "source_quote": (str(raw.get("source_quote") or "").strip() or None),
        "summary": (str(raw.get("summary") or "").strip() or None),
        "questions": questions,
        "category": cat,
        "entities": entities,
        "source_anchor": (str(raw.get("source_anchor") or "").strip() or None),
        "confidence": conf,
        "is_inference": bool(raw.get("is_inference", False)),
    }


def validate_digest(payload: Any) -> tuple[str, list[dict]]:
    """Validate/coerce the LLM digest payload -> (document_summary, units)."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DigestError(f"payload is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DigestError("top-level payload is not an object")
    units_raw = payload.get("units")
    if not isinstance(units_raw, list):
        raise DigestError("'units' is missing or not a list")
    units = [_coerce_unit(u) for u in units_raw]
    summary = str(payload.get("document_summary") or "").strip()
    return summary, units


# --------------------------------------------------------------------------- pipeline
class KnowledgePipeline:
    """Orchestrates digest -> embed -> index for one document.

    Injected deps (testable): ``embedder`` (GeminiEmbedder-compatible) and
    ``llm_json`` ((system, user) -> json text). Both run inside the RQ worker.
    """

    def __init__(self, db: AsyncSession, embedder: Embedder, llm_json: LLMJson) -> None:
        self.db = db
        self.embedder = embedder
        self.llm_json = llm_json

    async def run(self, doc) -> None:
        """Full pipeline for ``doc`` (KnowledgeDocument). Mutates + commits."""
        await self._set_stage(doc, "DIGESTING", status="PROCESSING", error=None)
        raw = doc.raw_text or ""
        sections = split_for_digest(raw)
        all_units: list[dict] = []
        summary_parts: list[str] = []
        for section in sections:
            summary, units = await self._digest_section(section)
            all_units.extend(units)
            if summary:
                summary_parts.append(summary)

        await self._set_stage(doc, "EMBEDDING")
        await self._store_units(doc, all_units)

        doc.digest_summary = " ".join(summary_parts).strip() or None
        flagged = [i for i, u in enumerate(all_units) if u["confidence"] == "low" or u["is_inference"]]
        doc.digest_meta = {
            "section_count": len(sections),
            "unit_count": len(all_units),
            "flagged_unit_indexes": flagged,
        }
        await self._set_stage(doc, "INDEXING")
        if doc.project_id is not None:
            try:
                await self.build_project_index(doc.project_id)
            except Exception as exc:  # noqa: BLE001 — index refresh is best-effort
                logger.warning("project index refresh failed: %s", exc)

        await self._set_stage(doc, "READY_FOR_REVIEW", status="READY_FOR_REVIEW")
        # rebuild the structured bus graph from the `documents` VIEW (verbatim SQL fn)
        try:
            await self.db.execute(text("SELECT rebuild_bus_timetable_from_documents()"))
            await self.db.commit()
        except Exception:  # noqa: BLE001 — rebuild is best-effort; never block ingest
            pass

    async def _digest_section(self, section: str) -> tuple[str, list[dict]]:
        """Call the LLM once per section; retry once on a malformed response."""
        last_err: str | None = None
        for attempt in range(2):
            try:
                raw = await self.llm_json(DIGEST_SYSTEM_PROMPT, section)
                payload = _parse_json_lenient(raw)
                return validate_digest(payload)
            except DigestError as exc:
                last_err = str(exc)
                logger.warning("digest attempt %d failed: %s", attempt + 1, last_err)
            except json.JSONDecodeError as exc:
                last_err = f"invalid JSON: {exc}"
                logger.warning("digest attempt %d not JSON: %s", attempt + 1, last_err)
        raise DigestError(f"digest failed after retry: {last_err}")

    async def _store_units(self, doc, units: list[dict]) -> None:
        await self.db.execute(
            text("DELETE FROM knowledge_chunks WHERE document_id = :did"), {"did": str(doc.id)}
        )
        if not units:
            await self.db.commit()
            return
        # Batch-embed one combined string per unit (content + summary + questions).
        embed_inputs = []
        for u in units:
            pieces = [u["content"]]
            if u["summary"]:
                pieces.append(u["summary"])
            pieces.extend(u["questions"])
            embed_inputs.append("\n".join(pieces))
        vectors = await self._embed_batch(embed_inputs)
        for idx, (u, vec) in enumerate(zip(units, vectors)):
            await self.db.execute(
                text(
                    "INSERT INTO knowledge_chunks "
                    "(document_id, chunk_index, content, embedding, metadata, project_id, "
                    " source_quote, summary, questions, category, entities, confidence) "
                    "VALUES (:did, :ci, :content, CAST(:emb AS vector), CAST(:meta AS jsonb), CAST(:pid AS uuid), "
                    "        :sq, :sm, CAST(:q AS text[]), :cat, CAST(:ent AS jsonb), :conf)"
                ),
                {
                    "did": str(doc.id),
                    "ci": idx,
                    "content": u["content"],
                    "emb": vec_literal(vec),
                    "meta": json.dumps(
                        {"source_anchor": u["source_anchor"], "is_inference": u["is_inference"]},
                        ensure_ascii=False,
                    ),
                    "pid": str(doc.project_id) if doc.project_id else None,
                    "sq": u["source_quote"],
                    "sm": u["summary"],
                    "q": u["questions"],
                    "cat": u["category"],
                    "ent": json.dumps(u["entities"], ensure_ascii=False),
                    "conf": u["confidence"],
                },
            )
        await self.db.commit()

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts; prefer a batch call when the embedder supports it."""
        batch = getattr(self.embedder, "batch", None)
        if callable(batch):
            return await batch(texts)  # type: ignore[misc]
        return [await self.embedder(t) for t in texts]

    async def build_project_index(self, project_id: uuid.UUID) -> None:
        """Regenerate the project's catalog card from its APPROVED units (master index)."""
        rows = (
            await self.db.execute(
                text(
                    "SELECT kc.content, kc.category FROM knowledge_chunks kc "
                    "JOIN knowledge_documents kd ON kd.id = kc.document_id "
                    "WHERE kd.project_id = :pid AND kd.status = 'APPROVED' "
                    "ORDER BY kc.created_at DESC LIMIT 200"
                ),
                {"pid": str(project_id)},
            )
        ).all()
        if not rows:
            return
        corpus = "\n".join(f"- [{r.category}] {r.content}" for r in rows)
        raw = await self.llm_json(INDEX_SYSTEM_PROMPT, corpus)
        card = _parse_json_lenient(raw)
        if not isinstance(card, dict):
            return
        await self.db.execute(
            text(
                "UPDATE projects SET summary = :summary, index_card = CAST(:card AS jsonb) "
                "WHERE id = :pid"
            ),
            {
                "summary": str(card.get("summary") or "").strip() or None,
                "card": json.dumps(card, ensure_ascii=False),
                "pid": str(project_id),
            },
        )
        await self.db.commit()

    async def _set_stage(self, doc, stage: str, *, status: str | None = None, error: str | None = None) -> None:
        doc.stage = stage
        if status is not None:
            # late import to avoid a circular at module load
            from app.models.knowledge import KnowledgeStatus

            doc.status = KnowledgeStatus(status)
        if error is not None:
            doc.error = None
        await self.db.commit()


def _parse_json_lenient(raw: str) -> Any:
    """Parse JSON, tolerating a surrounding ```json fence (some models add it)."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.split("```", 2)
        # s == ['', 'json\n...body...', ' maybe trailing']  or  ['', '\nbody\n','...']
        s = s[1] if len(s) > 1 else ""
        if s.lower().startswith("json"):
            s = s[4:]
    return json.loads(s.strip() or "{}")
