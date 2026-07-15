"""Phase 5: the neutral ``app.prompts`` layer imports cleanly + prompts are non-empty.

Guards against a bad edit / accidental blank prompt, and confirms the layer has no
graph/services imports (the whole point of extracting it from ``app.graph``).
"""


def test_prompts_package_has_no_graph_or_services_imports():
    import ast

    import app.prompts.candidate_extraction as mod

    tree = ast.parse(open(mod.__file__).read()).body
    for node in tree:
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("app.graph"), (
                f"app.prompts must not import graph (upward edge): {node.module}"
            )
            assert not node.module.startswith("app.services"), (
                f"app.prompts must not import services (upward edge): {node.module}"
            )


def test_candidate_extraction_prompt_is_non_empty_and_shaped():
    from app.prompts.candidate_extraction import CANDIDATE_EXTRACT_SYSTEM_PROMPT

    prompt = CANDIDATE_EXTRACT_SYSTEM_PROMPT
    assert prompt.strip().lower().startswith("bạn là")
    assert "json" in prompt.lower()
    assert "lead_patch" in prompt
    assert "memory_facts" in prompt
    assert "contact_intent" in prompt
    assert "intent_confidence" in prompt
    assert "phản hồi của bot và ghi chú đã lưu không phải bằng chứng intent" in prompt.lower()
    assert "mỗi dòng đúng một sự thật" in prompt.lower()
    assert "không tóm tắt" in prompt.lower()
    assert "không diễn đạt lại" in prompt.lower()
    assert "ghi chú đã lưu" in prompt.lower()
