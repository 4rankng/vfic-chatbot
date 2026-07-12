"""Tests for grounding enforcement — prevents citing job_ids not in retrieved data.

Pure-function tests: no DB, no LLM. The agent-loop wiring is tested via the
existing graph client integration path (requires langchain).
"""

from __future__ import annotations

from app.graph.grounding import (
    extract_cited_job_ids,
    extract_surfaced_job_ids,
    validate_grounding,
)

# Stable test UUIDs
JOB_A = "11111111-aaaa-4bbb-8ccc-222222222222"
JOB_B = "33333333-dddd-4eee-9fff-444444444444"
JOB_FAKE = "55555555-6666-4777-8888-999999999999"


# --- ID extraction -----------------------------------------------------------


def test_extract_surfaced_ids_from_tagged_form():
    tool_result = f"- Nhân viên kho (id={JOB_A}); lương 10tr"
    assert extract_surfaced_job_ids([tool_result]) == {JOB_A}


def test_extract_surfaced_ids_handles_multiple_results():
    results = [f"id={JOB_A}", f"id={JOB_B}"]
    assert extract_surfaced_job_ids(results) == {JOB_A, JOB_B}


def test_extract_cited_ids_catches_bare_uuid():
    reply = f"Theo tin tuyển dụng {JOB_A}, lương là 10 triệu."
    assert extract_cited_job_ids(reply) == {JOB_A}


def test_extract_cited_ids_catches_tagged_form():
    reply = f"Việc (id={JOB_B}) có KTX."
    assert extract_cited_job_ids(reply) == {JOB_B}


def test_extract_ids_empty_on_no_match():
    assert extract_surfaced_job_ids(["no ids here"]) == set()
    assert extract_cited_job_ids("just text") == set()


# --- validate_grounding ------------------------------------------------------


def test_validate_grounding_passes_when_all_cited_ids_were_surfaced():
    reply = f"Việc (id={JOB_A}) phù hợp với bạn."
    result = validate_grounding(reply, {JOB_A})
    assert result.is_grounded
    assert not result.hallucinated_ids
    assert result.sanitized_reply == reply


def test_validate_grounding_flags_hallucinated_id():
    """A cited ID not in the surfaced set is a hallucination."""
    reply = f"Việc (id={JOB_FAKE}) lương 20 triệu."
    result = validate_grounding(reply, {JOB_A})
    assert not result.is_grounded
    assert result.hallucinated_ids == frozenset({JOB_FAKE})
    assert result.reason == "cited_job_id_not_in_retrieved_set"


def test_validate_grounding_strips_hallucinated_id_from_reply():
    reply = f"Gợi ý việc (id={JOB_FAKE}) cho bạn."
    result = validate_grounding(reply, {JOB_A})
    assert JOB_FAKE not in result.sanitized_reply
    assert "[việc không xác định]" in result.sanitized_reply


def test_validate_grounding_no_citation_is_grounded():
    """A reply that cites no job IDs at all is trivially grounded (e.g. small talk)."""
    result = validate_grounding("Chào bạn, tôi có thể giúp gì?", set())
    assert result.is_grounded
    assert not result.hallucinated_ids


def test_validate_grounding_empty_surfaced_flags_all_citations():
    """If no job data was retrieved, any job_id citation is suspect."""
    reply = f"Việc (id={JOB_A}) tốt lắm."
    result = validate_grounding(reply, set())
    assert not result.is_grounded
    assert JOB_A in result.hallucinated_ids


def test_validate_grounding_preserves_grounded_content():
    """When some IDs are real and some fake, only the fake ones are stripped."""
    reply = f"Việc (id={JOB_A}) phù hợp; còn việc (id={JOB_FAKE}) cũng được."
    result = validate_grounding(reply, {JOB_A})
    assert not result.is_grounded
    assert result.hallucinated_ids == frozenset({JOB_FAKE})
    # Real ID preserved
    assert JOB_A in result.sanitized_reply
    # Fake ID stripped
    assert JOB_FAKE not in result.sanitized_reply
