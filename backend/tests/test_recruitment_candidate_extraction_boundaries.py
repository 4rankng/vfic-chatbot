"""Focused unit tests for recruitment candidate-extraction boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

from app.recruitment.application.candidate_extraction import CandidateExtractionUseCases
from app.recruitment.domain.candidate_extraction import (
    CandidateExtraction,
    finalize_candidate_extraction,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


class _Normalizer:
    def normalize_lead_patch(self, value: object, chat_id: str) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        lead_patch = {"zalo_id": chat_id, **value}
        return lead_patch

    def extract_self_reported_name(
        self,
        text: str | None,
        *,
        prev_bot_message: str | None = None,
    ) -> str | None:
        if text == "tôi tên Mai":
            return "Mai"
        if text == "Mai" and prev_bot_message == "Bạn tên gì?":
            return "Mai"
        return None


def _import_targets(path: Path) -> set[str]:
    targets: set[str] = set()
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.add(node.module)
    return targets


def test_domain_negative_intent_discards_candidate_payload_and_memory() -> None:
    result = finalize_candidate_extraction(
        lead_patch={"zalo_id": "zalo_1", "phone": "0912345678"},
        memory_facts=["Muốn ứng tuyển kho"],
        contact_intent="bot_testing",
        intent_confidence=0.99,
    )

    assert result == CandidateExtraction(
        lead_patch=None,
        memory_facts=[],
        contact_intent="uncertain",
        intent_confidence=0.0,
    )


async def test_application_extract_uses_ports_and_preserves_candidate_turn_shape() -> None:
    captured: dict[str, str] = {}

    async def extractor(system_prompt: str, turn: str) -> str:
        captured["system_prompt"] = system_prompt
        captured["turn"] = turn
        return (
            '{"lead_patch":{"desired_job":"lao động thời vụ"},'
            '"memory_facts":["Muốn làm thời vụ"],'
            '"contact_intent":"candidate","intent_confidence":0.99}'
        )

    use_cases = CandidateExtractionUseCases(
        normalizer=_Normalizer(),
        parse_memory_facts=lambda value: list(value or []),
        normalize_text=lambda text: text.lower(),
    )

    result = await use_cases.extract(
        extractor,
        system_prompt="prompt",
        user_text="tôi tên Mai",
        bot_output="Rất vui được biết bạn, Mai!",
        chat_id="zalo_1",
        existing_notes="Không có trình độ",
        oa_profile_display_name="Bé Gấu",
    )

    assert captured["system_prompt"] == "prompt"
    assert "GHI CHÚ ĐÃ LƯU" in captured["turn"]
    assert "TÊN HIỂN THỊ HỒ SƠ ZALO OA" in captured["turn"]
    assert result.lead_patch == {
        "zalo_id": "zalo_1",
        "desired_job": "lao động thời vụ",
        "name": "Mai",
    }
    assert result.memory_facts == ["Muốn làm thời vụ"]
    assert result.contact_intent == "candidate"
    assert result.intent_confidence == 0.99


def test_recruitment_candidate_extraction_modules_stay_free_of_orm_graph_and_provider_imports() -> None:
    application_path = (
        REPO_ROOT / "backend/app/recruitment/application/candidate_extraction.py"
    )
    domain_path = REPO_ROOT / "backend/app/recruitment/domain/candidate_extraction.py"

    forbidden_prefixes = (
        "sqlalchemy",
        "app.graph",
        "langchain",
        "openai",
        "google",
        "anthropic",
        "redis",
        "rq",
        "httpx",
        "app.models",
    )

    for path in (application_path, domain_path):
        targets = _import_targets(path)
        assert not any(
            target == prefix or target.startswith(f"{prefix}.")
            for target in targets
            for prefix in forbidden_prefixes
        ), f"forbidden import in {path.relative_to(REPO_ROOT)}: {sorted(targets)}"
