"""Phase 5: the neutral ``app.prompts`` layer imports cleanly + prompts are non-empty.

Guards against a bad edit / accidental blank prompt, and confirms the layer has no
graph/services imports (the whole point of extracting it from ``app.graph``).
"""


def test_prompts_package_has_no_graph_or_services_imports():
    import ast

    import app.prompts.lead_memory as mod

    tree = ast.parse(open(mod.__file__).read()).body
    for node in tree:
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("app.graph"), (
                f"app.prompts must not import graph (upward edge): {node.module}"
            )
            assert not node.module.startswith("app.services"), (
                f"app.prompts must not import services (upward edge): {node.module}"
            )


def test_lead_memory_prompts_are_non_empty_and_shaped():
    from app.prompts.lead_memory import LEAD_EXTRACT_SYSTEM_PROMPT, MEMORY_EXTRACT_PROMPT

    assert LEAD_EXTRACT_SYSTEM_PROMPT.strip().lower().startswith("bạn là")
    assert "json" in LEAD_EXTRACT_SYSTEM_PROMPT.lower()
    assert MEMORY_EXTRACT_PROMPT.strip().lower().startswith("bạn là")
    assert "mảng json" in MEMORY_EXTRACT_PROMPT.lower()
