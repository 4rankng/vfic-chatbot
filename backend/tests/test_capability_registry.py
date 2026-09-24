"""Pure contract tests for the code-owned capability registry."""

from __future__ import annotations

import json

import pytest

from app.capabilities import CapabilityDefinition, CapabilityRegistry, IndustryPackDefinition


def _registry(
    *,
    capabilities: tuple[CapabilityDefinition, ...] | None = None,
    packs: tuple[IndustryPackDefinition, ...] | None = None,
) -> CapabilityRegistry:
    return CapabilityRegistry(
        capabilities=capabilities
        or (
            CapabilityDefinition("conversation"),
            CapabilityDefinition("knowledge", ("conversation",)),
            CapabilityDefinition("job_advisory", ("knowledge", "conversation")),
        ),
        packs=packs
        or (
            IndustryPackDefinition(
                key="recruitment",
                version="1",
                capability_ids=("job_advisory", "conversation", "knowledge"),
                kernel_abi="1",
            ),
        ),
    )


def test_selected_pack_hash_is_canonical_across_registry_and_dependency_order() -> None:
    first = _registry()
    reordered = _registry(
        capabilities=(
            CapabilityDefinition("job_advisory", ("conversation", "knowledge")),
            CapabilityDefinition("knowledge", ("conversation",)),
            CapabilityDefinition("conversation"),
        ),
        packs=(
            IndustryPackDefinition(
                key="recruitment",
                version="1",
                capability_ids=("knowledge", "job_advisory", "conversation"),
                kernel_abi="1",
            ),
        ),
    )

    first_hash = first.pack_contract_hash("recruitment")

    assert reordered.pack_contract_hash("recruitment") == first_hash
    assert len(first_hash) == 64
    assert set(first_hash) <= set("0123456789abcdef")


def test_selected_pack_hash_ignores_unrelated_pack_contracts() -> None:
    recruitment_only = _registry()
    with_unrelated_pack = _registry(
        capabilities=(
            CapabilityDefinition("conversation"),
            CapabilityDefinition("knowledge", ("conversation",)),
            CapabilityDefinition("job_advisory", ("knowledge", "conversation")),
            CapabilityDefinition("unrelated_capability"),
        ),
        packs=(
            IndustryPackDefinition(
                key="recruitment",
                version="1",
                capability_ids=("conversation", "knowledge", "job_advisory"),
                kernel_abi="1",
            ),
            IndustryPackDefinition(
                key="unrelated-pack",
                version="27",
                capability_ids=("unrelated_capability",),
                kernel_abi="9",
            ),
        ),
    )

    assert with_unrelated_pack.pack_contract_hash(
        "recruitment"
    ) == recruitment_only.pack_contract_hash("recruitment")


@pytest.mark.parametrize(
    "changed_pack",
    [
        IndustryPackDefinition(
            key="recruitment",
            version="2",
            capability_ids=("conversation", "knowledge", "job_advisory"),
            kernel_abi="1",
        ),
        IndustryPackDefinition(
            key="recruitment",
            version="1",
            capability_ids=("conversation", "knowledge", "job_advisory"),
            kernel_abi="2",
        ),
    ],
)
def test_selected_pack_hash_changes_with_selected_pack_abi(
    changed_pack: IndustryPackDefinition,
) -> None:
    baseline = _registry().pack_contract_hash("recruitment")
    changed = _registry(packs=(changed_pack,)).pack_contract_hash("recruitment")

    assert changed != baseline


def test_selected_pack_hash_includes_capability_dependency_contract() -> None:
    baseline = _registry().pack_contract_hash("recruitment")
    changed_dependencies = _registry(
        capabilities=(
            CapabilityDefinition("conversation"),
            CapabilityDefinition("knowledge", ("conversation",)),
            CapabilityDefinition("job_advisory", ("knowledge",)),
        ),
    ).pack_contract_hash("recruitment")

    assert changed_dependencies != baseline


def test_selection_requires_the_complete_transitive_dependency_closure() -> None:
    registry = _registry()

    with pytest.raises(ValueError, match=r"job_advisory requires:.*knowledge"):
        registry.validate_selection("recruitment", ("conversation", "job_advisory"))

    with pytest.raises(ValueError, match=r"knowledge requires:.*conversation"):
        registry.validate_selection("recruitment", ("knowledge",))

    with pytest.raises(ValueError, match="duplicate capability IDs"):
        registry.validate_selection(
            "recruitment", ("job_advisory", "conversation", "knowledge", "knowledge")
        )

    assert registry.validate_selection(
        "recruitment", ("job_advisory", "conversation", "knowledge")
    ) == ("conversation", "job_advisory", "knowledge")


def test_selection_rejects_unknown_and_cross_pack_capability_ids() -> None:
    registry = _registry(
        capabilities=(
            CapabilityDefinition("conversation"),
            CapabilityDefinition("unrelated_capability"),
        ),
        packs=(
            IndustryPackDefinition(
                key="recruitment",
                version="1",
                capability_ids=("conversation",),
                kernel_abi="1",
            ),
            IndustryPackDefinition(
                key="unrelated-pack",
                version="1",
                capability_ids=("unrelated_capability",),
                kernel_abi="1",
            ),
        ),
    )

    with pytest.raises(ValueError, match="not in pack recruitment"):
        registry.validate_selection("recruitment", ("unrelated_capability",))

    with pytest.raises(ValueError, match="not in pack recruitment"):
        registry.validate_selection("recruitment", ("app.capabilities.recruitment",))


def test_shipped_pack_contract_hash_is_pinned_to_the_published_contract() -> None:
    """The live hash must equal the published v1 contract's hash.

    Every installed revision stores this hash, so an accidental change to the
    payload (a field added, an ordering tweak) would flag every production
    installation with PACK_CONTRACT_MISMATCH. The fixture is the published
    contract of record; only a deliberate contract bump may move this hash.
    """
    from pathlib import Path
    from app.capabilities.registry import get_capability_registry

    fixture = json.loads(
        (Path(__file__).parents[1] / "app/capabilities/recruitment_v1_contract.json").read_text()
    )
    assert get_capability_registry().pack_contract_hash("recruitment") == (
        fixture["contract_hash"]
    )
    assert fixture["contract_hash"] == (
        "2a7c602a2e222d14686fca6d86e12da34b0e2ce8ee6b4af32a95af7bd58622d9"
    )
    assert all("import" not in item for item in fixture["pack"]["capabilities"])
    assert all("factory" not in item for item in fixture["pack"]["capabilities"])


@pytest.mark.parametrize(
    ("field", "value", "label"),
    [
        ("api_routes", ("/x", "/x"), "route"),
        ("frontend_resources", ("items", "items"), "resource"),
        ("conversation_slots", ("row", "row"), "conversation slot"),
    ],
)
def test_registry_rejects_duplicates_inside_one_capability(
    field: str, value: tuple[str, str], label: str
) -> None:
    definition = CapabilityDefinition("conversation", **{field: value})
    with pytest.raises(ValueError, match=f"duplicate {label}"):
        _registry(
            capabilities=(definition,),
            packs=(
                IndustryPackDefinition(
                    key="recruitment",
                    version="1",
                    capability_ids=("conversation",),
                    kernel_abi="1",
                ),
            ),
        )


def test_pack_hash_covers_contract_schema_envelope(monkeypatch) -> None:
    import app.capabilities.registry as registry_module

    registry = _registry()
    baseline = registry.pack_contract_hash("recruitment")
    monkeypatch.setattr(registry_module, "PACK_CONTRACT_SCHEMA_VERSION", 2)
    assert registry.pack_contract_hash("recruitment") != baseline
