"""Contract tests for Cross-KB Retrieval & Reliable Stats (plan 260722-2300).

Pure unit tests covering the additive changes to ``availability`` and ``tools``. No DB
fixture is required because the dataclasses and sort/total logic are pure functions.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.graph.tools import _active_job_tool_result, list_active_jobs  # noqa: F401
from app.services.recommendation.availability import (
    ActiveJob,
    ActiveJobLookup,
    SortBy,  # noqa: F401
    select_matching_active_jobs,
)


def _job(**overrides) -> ActiveJob:
    values = {
        "id": "job-1",
        "title": "Công nhân sản xuất",
        "company_name": "VFIC Manufacturing",
        "factory_name": "Nhà máy A",
        "province": "Hải Phòng",
        "salary_min": 10_000_000,
        "salary_max": 14_000_000,
        "vacancy_count": 1,
    }
    values.update(overrides)
    return ActiveJob(**values)


# --- AC2: total count is independent of the top_k slice ---


def test_total_reflects_full_filter_match_independent_of_top_k():
    jobs = [
        _job(id=f"job-{i}", title=f"Vị trí {i}") for i in range(5)
    ]
    outcome = select_matching_active_jobs(jobs, top_k=3)
    assert outcome.status == "matched"
    assert len(outcome.jobs) == 3  # slice applied
    assert outcome.total == 5  # full count preserved


def test_total_defaults_to_zero_on_catalog_empty():
    outcome = select_matching_active_jobs([], top_k=3)
    assert outcome.status == "catalog_empty"
    assert outcome.total == 0


def test_total_defaults_to_zero_on_no_match():
    # A non-empty catalog that matches no filter is still total=0 for the filtered set.
    outcome = select_matching_active_jobs(
        [_job(title="Thợ hàn")], role="tài xế", top_k=3
    )
    assert outcome.status == "no_match"
    assert outcome.total == 0


def test_active_job_lookup_total_default_is_zero_for_one_arg_constructors():
    # Six 1-arg construction sites in the wild must not raise on .total access.
    lookup = ActiveJobLookup("unavailable")
    assert lookup.total == 0


# --- AC3: salary_desc ranks highest first across a merged source list ---


def test_salary_desc_returns_highest_paid_first():
    low = _job(id="low", salary_min=7_000_000, salary_max=9_000_000)
    high = _job(id="high", salary_min=12_000_000, salary_max=18_000_000)
    mid = _job(id="mid", salary_min=10_000_000, salary_max=14_000_000)
    outcome = select_matching_active_jobs([low, high, mid], sort_by="salary_desc")
    assert [j.id for j in outcome.jobs] == ["high", "mid", "low"]


# --- AC4: created_at sorts newest first ---


def test_created_at_sort_returns_newest_first():
    now = datetime.now(timezone.utc)
    oldest = _job(id="old", created_at=now - timedelta(days=10))
    newest = _job(id="new", created_at=now)
    mid = _job(id="mid", created_at=now - timedelta(days=3))
    outcome = select_matching_active_jobs(
        [oldest, newest, mid], sort_by="created_at"
    )
    assert [j.id for j in outcome.jobs] == ["new", "mid", "old"]


def test_created_at_sort_places_missing_timestamp_last():
    with_ts = _job(id="with-ts", created_at=datetime.now(timezone.utc))
    without_ts = _job(id="no-ts", created_at=None)
    outcome = select_matching_active_jobs(
        [without_ts, with_ts], sort_by="created_at"
    )
    # reverse=True puts the present timestamp first; None stays last.
    assert [j.id for j in outcome.jobs] == ["with-ts", "no-ts"]


# --- Phase 3: tool boundary whitelist + total propagation ---


def test_active_job_tool_result_includes_total_in_payload():
    result = _active_job_tool_result("matched", [], "ok", total=42)
    payload_line = next(
        line for line in result.splitlines() if line.startswith("ACTIVE_JOB_LOOKUP_JSON=")
    )
    payload = json.loads(payload_line[len("ACTIVE_JOB_LOOKUP_JSON="):])
    assert payload["total"] == 42


def test_active_job_tool_result_defaults_total_to_zero():
    result = _active_job_tool_result("catalog_empty", [], "ok")
    payload_line = next(
        line for line in result.splitlines() if line.startswith("ACTIVE_JOB_LOOKUP_JSON=")
    )
    payload = json.loads(payload_line[len("ACTIVE_JOB_LOOKUP_JSON="):])
    assert payload["total"] == 0
