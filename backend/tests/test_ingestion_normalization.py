"""Tests for Vietnamese text normalization (Tech-Lead Directive §9 stage 3)."""

from __future__ import annotations

from app.services.ingestion.normalization import (
    normalize_money,
    normalize_text,
    normalize_times,
    normalize_unicode,
    normalize_whitespace,
    normalize_query,
)


def test_normalize_unicode_nfc_composition():
    """Decomposed Vietnamese → composed NFC."""
    decomposed = "la\u0300ng"  # "l" + combining grave
    composed = "làng"
    assert normalize_unicode(decomposed) == composed


def test_normalize_whitespace_collapses_runs():
    assert normalize_whitespace("a    b\t\tc") == "a b c"
    # newlines preserved
    assert normalize_whitespace("a\n\n\nb") == "a\n\n\nb"


def test_normalize_whitespace_strips_line_ends():
    assert normalize_whitespace("a   \nb   ") == "a\nb"


def test_normalize_times_gio_to_24h():
    assert "6:00" in normalize_times("gửi 6 giờ")
    assert "6:00" in normalize_times("lúc 6h")


def test_normalize_times_chiều_to_pm():
    """6 giờ chiều → 18:00."""
    result = normalize_times("gửi 6 giờ chiều")
    assert "18:00" in result


def test_normalize_times_tối_to_pm():
    result = normalize_times("đóng cửa 7 giờ tối")
    assert "19:00" in result


def test_normalize_money_k_to_thousands():
    assert normalize_money("500k") == "500000"
    assert normalize_money("1.5k") == "1500"


def test_normalize_money_trieu_to_millions():
    assert normalize_money("5 triệu") == "5000000"
    assert normalize_money("1.5tr") == "1500000"
    assert normalize_money("2,5 triệu") == "2500000"


def test_normalize_text_pipeline_preserves_diacritics():
    """End-to-end: diacritics survive, time + money normalized."""
    raw = "Lương   15 triệu,  gửi  6 giờ sáng"
    out = normalize_text(raw)
    # Diacritics preserved
    assert "Lương" in out
    assert "gửi" in out
    # Whitespace collapsed
    assert "  " not in out
    # Money normalized
    assert "15000000" in out
    # Time normalized
    assert "6:00" in out


def test_normalize_query_lowercases_and_collapses():
    assert normalize_query("  Lương   BAO   Nhiêu  ") == "lương bao nhiêu"


def test_normalize_query_preserves_diacritics():
    """Diacritics preserved — 'lương' ≠ 'luong'."""
    assert normalize_query("LƯƠNG") == "lương"
    assert normalize_query("luong") == "luong"
    assert normalize_query("LƯƠNG") != normalize_query("luong")
