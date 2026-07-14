"""Tests for version-aware cache key resolution (Tech-Lead Directive §6)."""

from __future__ import annotations

from app.graph.cache_key import normalize_query, resolve_cache_key


def test_resolve_cache_key_deterministic():
    k1 = resolve_cache_key(query="lương bao nhiêu", knowledge_version="v1")
    k2 = resolve_cache_key(query="lương bao nhiêu", knowledge_version="v1")
    assert k1 == k2
    assert k1.to_string() == k2.to_string()


def test_different_queries_different_keys():
    k1 = resolve_cache_key(query="lương bao nhiêu", knowledge_version="v1")
    k2 = resolve_cache_key(query="mức lương là", knowledge_version="v1")
    assert k1 != k2


def test_different_active_job_different_keys():
    """Directive §6: key must include active_job_id so job-scoped answers don't leak."""
    k1 = resolve_cache_key(query="phúc lợi", knowledge_version="v1", active_job_id="job-A")
    k2 = resolve_cache_key(query="phúc lợi", knowledge_version="v1", active_job_id="job-B")
    assert k1 != k2


def test_different_knowledge_version_different_keys():
    """Directive §6: knowledge_version invalidates the cache on KB publish."""
    k1 = resolve_cache_key(query="lương", knowledge_version="v1")
    k2 = resolve_cache_key(query="lương", knowledge_version="v2")
    assert k1 != k2


def test_vietnamese_diacritics_preserved():
    """Diacritics are preserved (not stripped) — 'luong' ≠ 'lương'."""
    assert normalize_query("Lương Bao Nhiêu") == "lương bao nhiêu"
    k1 = resolve_cache_key(query="lương", knowledge_version="v1")
    k2 = resolve_cache_key(query="luong", knowledge_version="v1")
    assert k1 != k2


def test_whitespace_collapsed():
    assert normalize_query("  lương   bao   nhiêu  ") == "lương bao nhiêu"


def test_cache_key_hashable():
    """Must be usable as a dict key (single-flight coalescing depends on this)."""
    k = resolve_cache_key(query="test", knowledge_version="v1")
    d = {k: "value"}
    assert d[k] == "value"


def test_to_string_includes_all_directive_dimensions():
    """Directive §6 requires: tenant, language, query, job, company, knowledge_version."""
    k = resolve_cache_key(
        query="phúc lợi",
        knowledge_version="v9",
        active_job_id="job-1",
        active_company_id="co-1",
        language="vi",
        tenant_id="tenant-1",
    )
    s = k.to_string()
    assert "tenant-1" in s
    assert "v9" in s
    assert "job-1" in s
    assert "co-1" in s
    assert "vi" in s
    assert "answer:v2:" in s
