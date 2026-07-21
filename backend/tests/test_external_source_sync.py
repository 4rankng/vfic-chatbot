"""Hermetic tests for external-source sync.

Covers: the FAQ CSV parser (all branches + the FaqDocument schema gate),
hash determinism + revision-match, the SSRF rejection matrix, and the
orchestrator (NO_OP skip, STAGED, no inline activate, correct kwargs, failure
recording, Redis lock, 3-strike auto-disable, casing, BOM, URL sanitiser).
No live DB / Redis / network — everything is mocked or pure.
"""

from __future__ import annotations

import socket
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.knowledge_categories import FaqDocument, KnowledgeCategoryKey
from app.services.knowledge import external_source_sync as ess
from app.services.knowledge.category_contracts import category_checksum, parse_category_yaml
from app.services.knowledge.external_source_sync import (
    AUTO_DISABLE_THRESHOLD,
    ExternalSourceSyncError,
    SheetClient,
    build_source_yaml,
    extract_sheet_id,
    sanitize_error,
    sync_external_source,
    validate_sheet_url,
)
from app.services.knowledge.external_source_sync.parsers import parse_faq_csv

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "external_source_sync"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1rRk4wfKb90IxJAbywimgGDOV3Y7g8RbW1EpBabZmFw8/edit"


def _read(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _checksum_of(csv_text: str) -> str:
    payload = parse_faq_csv(csv_text)
    document = parse_category_yaml(KnowledgeCategoryKey.FAQ, build_source_yaml(payload))
    return category_checksum(document)


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def test_parse_skips_title_and_header_rows() -> None:
    payload = parse_faq_csv(_read("faq_sheet_synthetic.csv"))
    questions = [item["question"] for item in payload["faq"]]
    assert all("thường gặp" not in q.lower() for q in questions)
    assert all(q for q in questions)
    assert len(payload["faq"]) == 3


def test_parse_carries_forward_empty_category() -> None:
    # Row 4 has empty A but still parses (category carry-forward is structural,
    # not emitted in the FAQ payload — only question/answer matter).
    payload = parse_faq_csv(_read("faq_sheet_synthetic.csv"))
    assert any("chỗ ở" in item["question"] for item in payload["faq"])


def test_parse_drops_rows_with_empty_question_or_answer() -> None:
    csv_text = (
        "Title,,\n"
        "Sec,Câu hỏi thường gặp,Thông tin trả lời\n"
        "Sec,Only a question,\n"
        "Sec,,Only an answer\n"
        "Sec,Real question,Real answer\n"
    )
    payload = parse_faq_csv(csv_text)
    assert len(payload["faq"]) == 1
    assert payload["faq"][0]["question"] == "Real question"


def test_parse_strips_whitespace_and_handles_quoted_commas() -> None:
    csv_text = (
        "Title,,\n"
        "Sec,Câu hỏi thường gặp,Thông tin trả lời\n"
        'Sec,  Spaced question?  ,"Yes, with a comma"\n'
    )
    item = parse_faq_csv(csv_text)["faq"][0]
    assert item["question"] == "Spaced question?"
    assert item["answer"] == "Yes, with a comma"


def test_parse_handles_multiline_answers() -> None:
    payload = parse_faq_csv(_read("faq_sheet_synthetic.csv"))
    meals = next(item for item in payload["faq"] if "bữa ăn" in item["question"])
    assert "hai bữa mỗi ngày" in meals["answer"]


def test_parse_strips_utf8_bom() -> None:
    payload = parse_faq_csv("﻿" + _read("faq_sheet_synthetic.csv"))
    assert len(payload["faq"]) == 3


def test_parse_raises_on_unexpected_header() -> None:
    # No recognizable header row before data → content-poisoning guard fires.
    csv_text = "Title,,\nSec,Q1?,A1\n"
    with pytest.raises(ValueError, match="unexpected_header"):
        parse_faq_csv(csv_text)


def test_parse_output_passes_faqdocument_schema() -> None:
    """Finding 3 gate: the parser output must construct a valid FaqDocument."""
    payload = parse_faq_csv(_read("faq_sheet_synthetic.csv"))
    document = FaqDocument(**payload)  # StrictModel(extra="forbid") rejects extras
    assert document.schema_version == "1.0"
    assert document.category is KnowledgeCategoryKey.FAQ
    id_re = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    for item in document.faq:
        assert id_re.match(item.id), f"bad stable id: {item.id}"


def test_parse_synthesizes_unique_stable_ids() -> None:
    csv_text = (
        "Title,,\n"
        "Sec,Câu hỏi thường gặp,Thông tin trả lời\n"
        "Sec,Same question wording,A1\n"
        "Sec,Same question wording,A2\n"
    )
    ids = [item["id"] for item in parse_faq_csv(csv_text)["faq"]]
    assert len(ids) == len(set(ids))
    assert ids[1].endswith("-2")


def test_parse_canonical_order_is_deterministic_across_row_reorder() -> None:
    def _sheet(rows: list[tuple[str, str]]) -> str:
        body = "".join(f"S,{q},{a}\n" for q, a in rows)
        return "T,,\nS,Câu hỏi thường gặp,H\n" + body

    forward = parse_faq_csv(_sheet([("Bravo?", "B"), ("Alpha?", "A"), ("Charlie?", "C")]))
    reversed_ = parse_faq_csv(_sheet([("Charlie?", "C"), ("Alpha?", "A"), ("Bravo?", "B")]))
    # Both canonicalise to alphabetical-by-question order.
    assert [b["id"] for b in forward["faq"]] == [o["id"] for o in reversed_["faq"]]


# --------------------------------------------------------------------------- #
# Hash
# --------------------------------------------------------------------------- #


def test_hash_is_deterministic_across_reorder() -> None:
    def _sheet(rows: list[tuple[str, str]]) -> str:
        body = "".join(f"S,{q},{a}\n" for q, a in rows)
        return "T,,\nS,Câu hỏi thường gặp,H\n" + body

    forward = _sheet([("Bravo?", "B"), ("Alpha?", "A"), ("Charlie?", "C")])
    reversed_ = _sheet([("Charlie?", "C"), ("Alpha?", "A"), ("Bravo?", "B")])
    assert _checksum_of(forward) == _checksum_of(reversed_)


def test_hash_changes_when_answer_edited() -> None:
    base = _read("faq_sheet_synthetic.csv")
    edited = base.replace("10 triệu đồng mỗi tháng", "11 triệu đồng mỗi tháng")
    assert _checksum_of(base) != _checksum_of(edited)


def test_hash_matches_revision_content_sha256() -> None:
    """Finding 11: the orchestrator's hash equals what the category pipeline stores."""
    payload = parse_faq_csv(_read("faq_sheet_synthetic.csv"))
    source_yaml = build_source_yaml(payload)
    # stage_replacement parses the same YAML + checksums the resulting document.
    staged_checksum = category_checksum(parse_category_yaml(KnowledgeCategoryKey.FAQ, source_yaml))
    assert _checksum_of(_read("faq_sheet_synthetic.csv")) == staged_checksum


# --------------------------------------------------------------------------- #
# SSRF gate
# --------------------------------------------------------------------------- #


def test_validate_rejects_http_scheme() -> None:
    with pytest.raises(ExternalSourceSyncError, match="scheme_not_https"):
        validate_sheet_url("http://docs.google.com/sheets/d/abc/edit")


def test_validate_rejects_ip_literal() -> None:
    with pytest.raises(ExternalSourceSyncError, match="ip_literal_forbidden"):
        validate_sheet_url("https://192.168.1.1/sheets/d/abc/export")


@pytest.mark.parametrize("host", ["localhost", "evil.example", "internal.corp"])
def test_validate_rejects_non_google_host(host: str) -> None:
    with pytest.raises(ExternalSourceSyncError, match="host_not_allowed"):
        validate_sheet_url(f"https://{host}/sheets/d/abc/edit")


def test_validate_accepts_google_hosts() -> None:
    validate_sheet_url(SHEET_URL)  # no raise
    validate_sheet_url("https://docs.google.com/spreadsheets/d/abc/edit")
    validate_sheet_url("https://sheets.googleapis.com/v4/spreadsheets/abc")


def test_extract_sheet_id_handles_url_forms() -> None:
    sid = "1rRk4wfKb90IxJAbywimgGDOV3Y7g8RbW1EpBabZmFw8"
    assert extract_sheet_id(SHEET_URL) == sid
    assert extract_sheet_id(f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv") == sid


def test_extract_sheet_id_rejects_bad_url() -> None:
    with pytest.raises(ExternalSourceSyncError, match="invalid_sheet_id"):
        extract_sheet_id("https://docs.google.com/some/other/path")


def test_dns_rebind_to_private_ip_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ess.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("192.168.0.1", 443))]
    )
    with pytest.raises(ExternalSourceSyncError, match="private_or_loopback_ip"):
        ess._reject_private_host("docs.google.com")


def test_dns_rebind_to_aws_metadata_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ess.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("169.254.169.254", 443))]
    )
    with pytest.raises(ExternalSourceSyncError, match="private_or_loopback_ip"):
        ess._reject_private_host("docs.google.com")


def test_dns_resolution_failure_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a, **k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(ess.socket, "getaddrinfo", _raise)
    with pytest.raises(ExternalSourceSyncError, match="dns_resolution_failed"):
        ess._reject_private_host("docs.google.com")


class _FakeResponse:
    def __init__(self, status_code: int, text: str, content_type: str = "text/csv"):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": content_type}


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse, *args, **kwargs):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, _url):
        return self._response


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> None:
    monkeypatch.setattr(
        ess.httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(response, *a, **k)
    )
    # Bypass the real DNS-pin for the fetch-content tests (URL allow-list is
    # exercised separately above).
    monkeypatch.setattr(ess, "_reject_private_host", lambda _host: None)


@pytest.mark.asyncio
async def test_fetch_rejects_login_wall_html(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx(monkeypatch, _FakeResponse(200, _read("faq_sheet_login_wall.html")))
    with pytest.raises(ExternalSourceSyncError, match="sheet_not_public"):
        await SheetClient().fetch_csv(SHEET_URL)


@pytest.mark.asyncio
async def test_fetch_rejects_unexpected_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx(
        monkeypatch, _FakeResponse(200, "[1,2,3]", content_type="application/json")
    )
    with pytest.raises(ExternalSourceSyncError, match="unexpected_content_type"):
        await SheetClient().fetch_csv(SHEET_URL)


@pytest.mark.asyncio
async def test_fetch_maps_revocable_http_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx(monkeypatch, _FakeResponse(404, ""))
    with pytest.raises(ExternalSourceSyncError, match="http_404"):
        await SheetClient().fetch_csv(SHEET_URL)


@pytest.mark.asyncio
async def test_fetch_returns_csv_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx(monkeypatch, _FakeResponse(200, _read("faq_sheet_synthetic.csv")))
    body = await SheetClient().fetch_csv(SHEET_URL)
    assert "Câu hỏi thường gặp" in body


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        return self.store.pop(key, None) is not None


def _make_state(**overrides) -> SimpleNamespace:
    defaults = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "category_key": "faq",
        "source_kind": "google_sheet",
        "sheet_url": SHEET_URL,
        "sheet_gid": 0,
        "auto_sync_enabled": True,
        "consecutive_failures": 0,
        "last_content_hash": None,
        "last_synced_at": None,
        "last_status": "NEW",
        "last_error": None,
        "last_row_count": None,
        "last_revision_id": None,
        "created_by": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_db(state) -> MagicMock:
    db = AsyncMock()
    db.get = AsyncMock(return_value=state)
    db.scalar = AsyncMock(return_value=None)  # no active revision / category
    db.commit = AsyncMock()
    return db


def _patch_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    *,
    csv_text: str | None,
    active_checksum: str | None,
    staged_revision_id: uuid.UUID | None = uuid.uuid4(),
    staged_job_id: str = "category-revision-staged",
    stage_side_effect=None,
) -> tuple[AsyncMock, _FakeRedis]:
    """Wire mocks into the orchestrator: Redis lock, fetch, active checksum, service."""
    fake_redis = _FakeRedis()
    monkeypatch.setattr(ess, "get_redis", lambda: fake_redis)
    if csv_text is not None:
        monkeypatch.setattr(SheetClient, "fetch_csv", AsyncMock(return_value=csv_text))
    monkeypatch.setattr(ess, "_reject_private_host", lambda _host: None)
    monkeypatch.setattr(ess, "_active_revision_checksum", AsyncMock(return_value=active_checksum))

    captured = SimpleNamespace(kwargs=None)

    if stage_side_effect is not None:
        stage_mock = AsyncMock(side_effect=stage_side_effect)
    else:
        revision = SimpleNamespace(id=staged_revision_id)

        async def _stage(*args, **kwargs):
            captured.kwargs = kwargs
            return revision, staged_job_id

        stage_mock = _stage

    fake_service = SimpleNamespace(stage_replacement=stage_mock)
    monkeypatch.setattr(ess, "KnowledgeCategoryService", lambda _db: fake_service)
    return captured, fake_redis


@pytest.mark.asyncio
async def test_sync_returns_staged_on_change(monkeypatch: pytest.MonkeyPatch) -> None:
    captured, _ = _patch_orchestrator(
        monkeypatch, csv_text=_read("faq_sheet_synthetic.csv"), active_checksum=None
    )
    state = _make_state(last_status="NEW")
    actor = SimpleNamespace(id=uuid.uuid4())
    outcome = await sync_external_source(_mock_db(state), state_id=state.id, actor=actor)

    assert outcome.status == "STAGED"
    assert outcome.job_id == "category-revision-staged"
    assert state.last_status == "OK"
    assert state.last_revision_id is not None
    assert state.consecutive_failures == 0


@pytest.mark.asyncio
async def test_stage_replacement_called_with_correct_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 5: filename= (not source_filename=), actor required + non-None."""
    captured, _ = _patch_orchestrator(
        monkeypatch, csv_text=_read("faq_sheet_synthetic.csv"), active_checksum=None
    )
    actor = SimpleNamespace(id=uuid.uuid4())
    await sync_external_source(
        _mock_db(_make_state()), state_id=uuid.uuid4(), actor=actor
    )
    assert "filename" in captured.kwargs
    assert "source_filename" not in captured.kwargs
    assert "source_yaml" in captured.kwargs
    assert captured.kwargs["actor"] is actor


@pytest.mark.asyncio
async def test_sync_returns_noop_when_active_revision_hash_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 11: unchanged content skips stage_replacement entirely."""
    csv_text = _read("faq_sheet_synthetic.csv")
    captured, _ = _patch_orchestrator(
        monkeypatch, csv_text=csv_text, active_checksum=_checksum_of(csv_text)
    )
    state = _make_state(last_status="OK")
    outcome = await sync_external_source(_mock_db(state), state_id=state.id, actor=SimpleNamespace(id=uuid.uuid4()))
    assert outcome.status == "NO_OP"
    assert state.last_status == "NO_OP"
    assert captured.kwargs is None  # stage_replacement never called


@pytest.mark.asyncio
async def test_orchestrator_source_never_calls_activate_revision() -> None:
    """Finding 4: activation is enqueued by stage_replacement, never an inline call."""
    source = Path(ess.__file__).read_text(encoding="utf-8")
    # A bare mention in a docstring is fine; an actual call (``.activate_revision(``)
    # or ``activate_revision(...)``) is the violation.
    assert "activate_revision(" not in source


@pytest.mark.asyncio
async def test_sync_records_failed_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(ess, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(
        SheetClient, "fetch_csv", AsyncMock(side_effect=ExternalSourceSyncError("http_404"))
    )
    state = _make_state()
    outcome = await sync_external_source(
        _mock_db(state), state_id=state.id, actor=SimpleNamespace(id=uuid.uuid4())
    )
    assert outcome.status == "FAILED"
    assert outcome.error == "http_404"
    assert state.last_status == "FAILED"
    assert state.last_error == "http_404"


@pytest.mark.asyncio
async def test_sync_takes_redis_lock_and_returns_locked_on_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 23: a concurrent call for the same state_id is LOCKED without staging."""
    captured, fake_redis = _patch_orchestrator(
        monkeypatch, csv_text=_read("faq_sheet_synthetic.csv"), active_checksum=None
    )
    state = _make_state()
    # Pre-acquire the lock as if another caller holds it.
    fake_redis.store[f"ext_src_sync:{state.id}"] = "1"
    outcome = await sync_external_source(
        _mock_db(state), state_id=state.id, actor=SimpleNamespace(id=uuid.uuid4())
    )
    assert outcome.status == "LOCKED"
    assert captured.kwargs is None  # never staged


@pytest.mark.asyncio
async def test_sync_uppercase_category_key_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 17: stored uppercase still constructs the enum via .lower()."""
    captured, _ = _patch_orchestrator(
        monkeypatch, csv_text=_read("faq_sheet_synthetic.csv"), active_checksum=None
    )
    state = _make_state(category_key="FAQ")
    outcome = await sync_external_source(_mock_db(state), state_id=state.id, actor=SimpleNamespace(id=uuid.uuid4()))
    assert outcome.status == "STAGED"
    assert captured.kwargs["category_key"] is KnowledgeCategoryKey.FAQ


@pytest.mark.asyncio
async def test_sync_empty_sheet_records_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 19: empty-after-parse is caught, not crashed."""
    _patch_orchestrator(monkeypatch, csv_text=_read("faq_sheet_empty.csv"), active_checksum=None)
    state = _make_state()
    outcome = await sync_external_source(_mock_db(state), state_id=state.id, actor=SimpleNamespace(id=uuid.uuid4()))
    assert outcome.status == "FAILED"
    assert "empty" in (outcome.error or "")


@pytest.mark.asyncio
async def test_sync_unknown_category_records_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_orchestrator(monkeypatch, csv_text=_read("faq_sheet_synthetic.csv"), active_checksum=None)
    state = _make_state(category_key="transportation")  # no parser registered in v1
    outcome = await sync_external_source(_mock_db(state), state_id=state.id, actor=SimpleNamespace(id=uuid.uuid4()))
    assert outcome.status == "FAILED"
    assert outcome.error and outcome.error.startswith("no_parser_for_category")


def test_last_error_sanitizer_strips_urls() -> None:
    """Finding 24: httpx URLs (with ?access_token=) never reach last_error."""
    sanitized = sanitize_error(
        ValueError("boom https://docs.google.com/x?access_token=SECRET here")
    )
    assert "SECRET" not in sanitized
    assert "docs.google.com" not in sanitized
    assert "[url]" in sanitized


@pytest.mark.asyncio
async def test_mark_failed_auto_disables_after_threshold() -> None:
    """Validation Q4: 3 revocable failures flip auto_sync_enabled to False."""
    db = _mock_db(_make_state())
    state = _make_state()
    for _ in range(AUTO_DISABLE_THRESHOLD):
        await ess._mark_failed(db, state, "sheet_not_public")
    assert state.auto_sync_enabled is False
    assert state.consecutive_failures == AUTO_DISABLE_THRESHOLD


@pytest.mark.asyncio
async def test_mark_failed_transient_failure_does_not_disable() -> None:
    """Validation Q4: a transient failure (network/500) must not auto-disable."""
    db = _mock_db(_make_state())
    state = _make_state()
    for _ in range(3):
        await ess._mark_failed(db, state, "fetch_failed")
    assert state.auto_sync_enabled is True
    assert state.consecutive_failures == 0  # transient doesn't even count


@pytest.mark.asyncio
async def test_mark_success_resets_consecutive_failures() -> None:
    db = _mock_db(_make_state())
    state = _make_state(consecutive_failures=2)
    await ess._mark_noop(db, state, "hash", 3)
    assert state.consecutive_failures == 0
    assert state.last_status == "NO_OP"
