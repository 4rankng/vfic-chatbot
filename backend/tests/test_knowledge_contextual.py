"""Contextual Retrieval prefix (index-time) — unit tests.

Covers the deterministic prefix builder, the env toggle, and the pipeline's
embed-input assembly (digest units get the prefix; canonical units keep their
spec-owned ``contextual_text`` header and are never double-prefixed).
"""

from types import SimpleNamespace

from app.core.config import Settings
from app.services.knowledge import contextual
from app.services.knowledge.contextual import (
    CONTEXTUAL_PREFIX_VERSION,
    build_chunk_context_prefix,
    contextual_embed_input,
)
from app.services.knowledge.pipeline import KnowledgePipeline


# --------------------------------------------------------------------------- builder
def test_prefix_assembles_document_and_unit_metadata():
    prefix = build_chunk_context_prefix(
        doc_title="LG Display - Lương & phụ cấp.docx",
        doc_summary="Chính sách lương thưởng của LG Display tại Hải Phòng.",
        unit_summary="Lương cơ bản 5.5 triệu",
        source_anchor="§3",
        category="salary",
    )
    assert prefix is not None
    assert prefix.startswith("Tài liệu: LG Display - Lương & phụ cấp.docx. ")
    assert "Tóm tắt tài liệu: Chính sách lương thưởng" in prefix
    assert "Nội dung: Lương cơ bản 5.5 triệu — chủ đề lương/thu nhập (§3)." in prefix
    assert CONTEXTUAL_PREFIX_VERSION  # marker exists; the template moves with it


def test_prefix_metadata_first_without_llm_call():
    # Same inputs twice → byte-identical prefix (no LLM in the path).
    kwargs = dict(doc_title="a.md", doc_summary="tóm tắt", unit_summary="đoạn")
    assert build_chunk_context_prefix(**kwargs) == build_chunk_context_prefix(**kwargs)


def test_prefix_title_only_still_useful_but_empty_metadata_is_none():
    assert build_chunk_context_prefix(doc_title="tuyen-dung.docx") == (
        "Tài liệu: tuyen-dung.docx."
    )
    # A summary identical to the title adds nothing.
    assert build_chunk_context_prefix(
        doc_title="x", doc_summary="x", unit_summary=None
    ) == "Tài liệu: x."
    assert build_chunk_context_prefix(doc_title=None, doc_summary="   ") is None
    assert build_chunk_context_prefix(doc_title="", doc_summary="") is None


def test_prefix_unknown_category_renders_no_topic_label():
    prefix = build_chunk_context_prefix(
        doc_title="d", unit_summary="u", category="mystery"
    )
    assert prefix is not None
    assert "chủ đề" not in prefix


def test_prefix_is_bounded():
    prefix = build_chunk_context_prefix(
        doc_title="T" * 500,
        doc_summary="S" * 500,
        unit_summary="U" * 500,
        source_anchor="A" * 200,
        category="job",
    )
    assert prefix is not None
    assert len(prefix) <= 601  # 600 + the terminating ellipsis char


# --------------------------------------------------------------------------- toggle
def _set_toggle(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(
        contextual, "get_settings", lambda: SimpleNamespace(rag_contextual_enabled=enabled)
    )


def test_toggle_defaults_on():
    assert Settings().rag_contextual_enabled is True


def test_embed_input_off_returns_base_and_stamps_none(monkeypatch):
    _set_toggle(monkeypatch, False)
    unit: dict = {"summary": "s", "source_anchor": "§1", "category": "job"}
    out = contextual_embed_input(unit, "nội dung", doc_title="doc.md")
    assert out == "nội dung"
    assert unit["contextual_prefix"] is None


def test_embed_input_on_prepends_prefix_and_stamps_it(monkeypatch):
    _set_toggle(monkeypatch, True)
    unit: dict = {"summary": "lương cơ bản", "source_anchor": "§1", "category": "salary"}
    out = contextual_embed_input(unit, "nội dung", doc_title="doc.md", doc_summary="tóm tắt")
    assert out.startswith("Tài liệu: doc.md. Tóm tắt tài liệu: tóm tắt.")
    assert out.endswith("\nnội dung")
    assert unit["contextual_prefix"] == build_chunk_context_prefix(
        doc_title="doc.md",
        doc_summary="tóm tắt",
        unit_summary="lương cơ bản",
        source_anchor="§1",
        category="salary",
    )


# --------------------------------------------------------------------------- pipeline
class _RecordingEmbedder:
    """GeminiEmbedder-compatible single-text embedder that records inputs."""

    def __init__(self):
        self.texts: list[str] = []

    async def embed(self, t):
        self.texts.append(t)
        return [0.01] * 3072

    __call__ = embed


class _RecordingChunkRepo:
    def __init__(self):
        self.stored: list[tuple] = []

    async def replace_for_doc(self, doc, units_with_vectors):
        self.stored.append((doc, [u for u, _ in units_with_vectors]))


def _pipeline() -> tuple[KnowledgePipeline, _RecordingEmbedder, _RecordingChunkRepo]:
    embedder = _RecordingEmbedder()
    repo = _RecordingChunkRepo()
    pipeline = KnowledgePipeline(db=None, embedder=embedder, llm_json=None)
    pipeline.chunks = repo
    return pipeline, embedder, repo


def _digest_unit(content: str, **overrides) -> dict:
    unit = {
        "content": content,
        "source_quote": content,
        "summary": f"tóm tắt {content[:10]}",
        "questions": [f"{content[:10]}?"],
        "category": "salary",
        "entities": {},
        "source_anchor": "§1",
        "confidence": "high",
        "is_inference": False,
    }
    unit.update(overrides)
    return unit


async def test_store_units_prefixes_digest_units(monkeypatch):
    _set_toggle(monkeypatch, True)
    pipeline, embedder, repo = _pipeline()
    doc = SimpleNamespace(file_name="luong-lg.md", metadata_=None)
    units = [_digest_unit("Lương cơ bản 5.5 triệu")]

    await pipeline._store_units(doc, units, doc_summary="chính sách lương")

    (prefixed_input,) = embedder.texts
    assert prefixed_input.startswith("Tài liệu: luong-lg.md. Tóm tắt tài liệu: chính sách lương.")
    # The chunk's own summary + questions still ride as their own lines.
    assert "\ntóm tắt Lương cơ b" in prefixed_input
    assert prefixed_input.endswith("\nLương cơ b?")
    # Prefix stored separately; content verbatim.
    stored_unit = repo.stored[0][1][0]
    assert stored_unit["content"] == "Lương cơ bản 5.5 triệu"
    assert stored_unit["contextual_prefix"].startswith("Tài liệu: luong-lg.md")


async def test_store_units_never_double_prefixes_canonical_units(monkeypatch):
    _set_toggle(monkeypatch, True)
    pipeline, embedder, repo = _pipeline()
    doc = SimpleNamespace(file_name="canonical.md", metadata_=None)
    units = [_digest_unit("Nội dung canonical", contextual_text="Document: X\n\nNội dung canonical")]

    await pipeline._store_units(doc, units, doc_summary="tóm tắt")

    (embed_input,) = embedder.texts
    assert embed_input.startswith("Document: X\n\nNội dung canonical")
    assert "Tài liệu:" not in embed_input
    stored_unit = repo.stored[0][1][0]
    assert "contextual_prefix" not in stored_unit


async def test_store_units_off_keeps_legacy_embed_input(monkeypatch):
    _set_toggle(monkeypatch, False)
    pipeline, embedder, repo = _pipeline()
    doc = SimpleNamespace(file_name="luong-lg.md", metadata_=None)
    units = [_digest_unit("Lương cơ bản 5.5 triệu")]

    await pipeline._store_units(doc, units, doc_summary="chính sách lương")

    (embed_input,) = embedder.texts
    assert embed_input == "Lương cơ bản 5.5 triệu\ntóm tắt Lương cơ b\nLương cơ b?"
    stored_unit = repo.stored[0][1][0]
    assert stored_unit["contextual_prefix"] is None
