"""Pure contract tests for the code-owned capability registry."""

from __future__ import annotations

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
            CapabilityDefinition("product_catalog"),
        ),
        packs=(
            IndustryPackDefinition(
                key="recruitment",
                version="1",
                capability_ids=("conversation", "knowledge", "job_advisory"),
                kernel_abi="1",
            ),
            IndustryPackDefinition(
                key="product_advisory",
                version="27",
                capability_ids=("product_catalog",),
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

    assert registry.validate_selection(
        "recruitment", ("job_advisory", "conversation", "knowledge", "knowledge")
    ) == ("conversation", "job_advisory", "knowledge")


def test_selection_rejects_unknown_and_cross_pack_capability_ids() -> None:
    registry = _registry(
        capabilities=(
            CapabilityDefinition("conversation"),
            CapabilityDefinition("product_catalog"),
        ),
        packs=(
            IndustryPackDefinition(
                key="recruitment",
                version="1",
                capability_ids=("conversation",),
                kernel_abi="1",
            ),
            IndustryPackDefinition(
                key="product_advisory",
                version="1",
                capability_ids=("product_catalog",),
                kernel_abi="1",
            ),
        ),
    )

    with pytest.raises(ValueError, match="not in pack recruitment"):
        registry.validate_selection("recruitment", ("product_catalog",))

    with pytest.raises(ValueError, match="not in pack recruitment"):
        registry.validate_selection("recruitment", ("app.capabilities.recruitment",))
