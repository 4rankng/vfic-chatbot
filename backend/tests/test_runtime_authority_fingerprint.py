"""Pure tests for deterministic runtime-authority fencing fingerprints."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.services.installation.authority import RuntimeAuthorityFingerprint


REVISION_ID = UUID("11111111-1111-4111-8111-111111111111")


def _fingerprint(**overrides: object) -> RuntimeAuthorityFingerprint:
    values: dict[str, object] = {
        "authority_generation": 7,
        "revision_id": REVISION_ID,
        "manifest_checksum": "a" * 64,
        "pack_contract_hash": "b" * 64,
        "persona_checksum": "c" * 64,
        "workflow_policy_checksum": "d" * 64,
        "provider_policy_checksum": "e" * 64,
        "template_checksums": {
            "template-b": "2" * 64,
            "template-a": "1" * 64,
        },
        "active_kb_vector": (
            ("knowledge-b", "4" * 64),
            ("knowledge-a", "3" * 64),
        ),
    }
    values.update(overrides)
    return RuntimeAuthorityFingerprint(**values)  # type: ignore[arg-type]


def test_checksum_is_canonical_for_mapping_and_kb_vector_order() -> None:
    first = _fingerprint()
    reordered = _fingerprint(
        template_checksums={
            "template-a": "1" * 64,
            "template-b": "2" * 64,
        },
        active_kb_vector=(
            ("knowledge-a", "3" * 64),
            ("knowledge-b", "4" * 64),
        ),
    )

    checksum = first.checksum()

    assert reordered.checksum() == checksum
    assert first.checksum() == checksum
    assert len(checksum) == 64
    assert set(checksum) <= set("0123456789abcdef")


def test_generation_change_invalidates_fingerprint_even_after_revision_rollback() -> None:
    original_revision_generation = _fingerprint(authority_generation=7)
    rolled_back_same_revision = _fingerprint(authority_generation=9)

    assert rolled_back_same_revision.revision_id == original_revision_generation.revision_id
    assert rolled_back_same_revision.checksum() != original_revision_generation.checksum()


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("manifest_checksum", "f" * 64),
        ("pack_contract_hash", "f" * 64),
        ("persona_checksum", "f" * 64),
        ("workflow_policy_checksum", "f" * 64),
        ("provider_policy_checksum", "f" * 64),
        ("template_checksums", {"template-a": "f" * 64}),
        ("active_kb_vector", (("knowledge-a", "f" * 64),)),
    ],
)
def test_each_pinned_runtime_artifact_contributes_to_checksum(
    field: str,
    changed_value: object,
) -> None:
    baseline = _fingerprint().checksum()

    assert _fingerprint(**{field: changed_value}).checksum() != baseline
