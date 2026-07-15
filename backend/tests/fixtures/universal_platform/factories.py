"""Factories with no business defaults or implicit sample rows."""

from __future__ import annotations

from copy import deepcopy


def installation_fixture(
    *,
    customer: dict,
    pack: str,
    capabilities: list[str],
    persona: dict,
    template: dict,
    golden_turns: list[dict],
    integrations: list[dict],
) -> dict:
    """Build test input only when every business choice is explicit."""
    return deepcopy(
        {
            "customer": customer,
            "pack": pack,
            "capabilities": capabilities,
            "persona": persona,
            "template": template,
            "golden_turns": golden_turns,
            "integrations": integrations,
        }
    )


def empty_installation_fixture() -> dict:
    """Represent a clean install, intentionally containing no business choice."""
    return {
        "customer": None,
        "pack": None,
        "persona": None,
        "templates": [],
        "integrations": [],
        "business_rows": [],
    }
