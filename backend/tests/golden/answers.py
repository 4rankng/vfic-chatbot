"""Golden answer set loader + deterministic fact-hit scoring (RAG pack B).

``answers.yaml`` is the answer-quality companion to ``golden/dataset.yaml``:
one entry per representative Vietnamese question, with the points a correct
reply must contain (điểm cần có) and an ``abstain`` flag for questions the KB
deliberately cannot answer. Every entry's ``ref`` names a case in
``tests/fixtures/rag_gold/cases.json`` so the eval harness can retrieve real
context for it through the production post-retrieval pipeline without a
database.

Pure functions only — no I/O beyond reading the YAML, no LLM. The LLM-judge
scoring lives in ``scripts/eval_answers.py`` (DeepEval); this module owns the
deterministic half: normalization, fact-hit matching, and the reference
answer text the judge is shown.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover — yaml is a backend dep
    yaml = None  # type: ignore[assignment]

ANSWERS_YAML = Path(__file__).resolve().parent / "answers.yaml"

# Shown to the LLM judge as expected_output for abstain entries.
ABSTAIN_REFERENCE = (
    "Không có thông tin trong dữ liệu cho câu hỏi này; "
    "câu trả lời đúng phải từ chối trả lời và không bịa số liệu."
)


@dataclass(frozen=True)
class AnswerGold:
    """One golden answer case: question + the points a correct reply carries."""

    id: str
    category: str
    ref: str
    question: str
    expected_answer_points: tuple[str, ...]
    abstain: bool = False

    def reference_answer(self) -> str:
        """The reference text the LLM judge grades against."""
        if self.abstain:
            return ABSTAIN_REFERENCE
        return "; ".join(self.expected_answer_points)


def normalize_text(text: str) -> str:
    """Diacritic-fold, case-fold, and whitespace-collapse ``text``.

    Used on BOTH sides of every fact-hit comparison so "7.500.000" matches
    "7.500.000", "Sơ yếu lý lịch" matches "so yeu lich", and an answer's
    formatting (line breaks, casing) never changes the score. Deliberately
    coarse: this is a floor metric, the LLM judge is the real grader.
    """
    folded = unicodedata.normalize("NFD", text or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.replace("đ", "d").replace("Đ", "D")
    return " ".join(folded.casefold().split())


def load_answer_gold(path: Path | str = ANSWERS_YAML) -> tuple[AnswerGold, ...]:
    """Parse ``answers.yaml`` into immutable :class:`AnswerGold` records."""
    if yaml is None:
        raise RuntimeError("PyYAML not installed; cannot load golden answer set")
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "entries" not in raw:
        raise ValueError(f"invalid golden answer set: missing 'entries' key in {path}")
    seen_ids: set[str] = set()
    entries: list[AnswerGold] = []
    for index, item in enumerate(raw["entries"]):
        if not isinstance(item, dict):
            raise ValueError(f"{path}[{index}]: entry must be a mapping")
        entry_id = str(item.get("id") or "").strip()
        if not entry_id:
            raise ValueError(f"{path}[{index}]: entry missing 'id'")
        if entry_id in seen_ids:
            raise ValueError(f"{path}: duplicate entry id {entry_id!r}")
        seen_ids.add(entry_id)
        question = str(item.get("question") or "").strip()
        if not question:
            raise ValueError(f"{path} entry {entry_id!r}: question is required")
        ref = str(item.get("ref") or "").strip()
        if not ref:
            raise ValueError(f"{path} entry {entry_id!r}: ref is required")
        abstain = bool(item.get("abstain", False))
        points = tuple(
            str(p).strip() for p in (item.get("expected_answer_points") or []) if str(p).strip()
        )
        if abstain and points:
            raise ValueError(
                f"{path} entry {entry_id!r}: abstain entries must not carry expected_answer_points"
            )
        if not abstain and not points:
            raise ValueError(
                f"{path} entry {entry_id!r}: non-abstain entries need expected_answer_points"
            )
        entries.append(
            AnswerGold(
                id=entry_id,
                category=str(item.get("category") or "general").strip(),
                ref=ref,
                question=question,
                expected_answer_points=points,
                abstain=abstain,
            )
        )
    return tuple(entries)


def fact_hit_rate(answer: str, gold: AnswerGold) -> float | None:
    """Fraction of ``gold``'s expected points present in ``answer``.

    Returns ``None`` for abstain entries (they carry no required points —
    their quality is judged by faithfulness, not by substring presence).
    """
    if gold.abstain:
        return None
    haystack = normalize_text(answer)
    hits = sum(1 for point in gold.expected_answer_points if normalize_text(point) in haystack)
    return hits / len(gold.expected_answer_points)
