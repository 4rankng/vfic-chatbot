#!/usr/bin/env python3
"""Answer-quality eval harness (RAG pack B) — DeepEval over the golden answer set.

Measures what the retrieval benchmark cannot: whether the bot's ANSWER is
faithful to the retrieved context, relevant to the question, and served from a
well-ordered context (contextual precision/recall). Two layers of scoring:

  * deterministic — precision/recall of the retrieved chunk ids against the
    gold set (``tests.rag_gold.precision``) and a fact-hit check of the answer
    against ``tests/golden/answers.yaml`` expected points. Offline, free,
    runs anywhere.
  * LLM-judge (DeepEval) — Faithfulness, AnswerRelevancy, ContextualPrecision,
    ContextualRecall. The judge is the app's own provider client
    (``app.graph.providers._chat_for_role``), so evals reuse the existing
    MiniMax/OpenRouter credentials — no new API keys.

Pipeline per case (``--answers live``):
  1. retrieve context through the REAL post-retrieval pipeline
     (``tests.services_runner.build_rows_for_case`` → ``rerank_if_enabled``)
     over the canned-embedding gold fixtures — the same fusion/rerank code
     production runs, minus Postgres;
  2. generate the answer with the app's agent LLM under the production persona
     (``app.graph.prompts.AGENT_SYSTEM_PROMPT``) grounded on that context;
  3. score with the two layers above.

P3-2 rerank decision: run with ``--rerank both`` to score the same set with
``rag_rerank_enabled`` off and on and print the comparison table. The decision
rule (documented in docs/decisions/0014-*.md) enables the flag only when mean
precision@3 lifts by >= 2.0 points.

Usage (from backend/, dev venv):

    .venv/bin/python -m scripts.eval_answers --rerank both --output /tmp/eval.json
    .venv/bin/python -m scripts.eval_answers --rerank off --no-answers   # retrieval-only
    .venv/bin/python -m scripts.eval_answers --rerank off --replay prev.json --judge off

The report JSON is self-contained (per-case answers + contexts), so
``--replay`` re-scores a previous run offline. ``--gate-output`` writes the
flat payload consumed by ``scripts/release_gate_check.py --answer-quality``.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

REPORT_SCHEMA = "answer-eval-report/1"
COMPARISON_SCHEMA = "answer-eval-comparison/1"
GATE_PAYLOAD_SCHEMA = "answer-quality-gate/1"

# P3-2 decision rule: enable the score-blend reranker only on a precision lift
# of at least this many percentage points (mean precision@3, same gold set).
RERANK_DECISION_PRECISION_LIFT_POINTS = 2.0

# Judge metrics keyed by their report field name. Order = report order.
JUDGE_METRICS: tuple[tuple[str, str], ...] = (
    ("faithfulness", "FaithfulnessMetric"),
    ("answer_relevancy", "AnswerRelevancyMetric"),
    ("contextual_precision", "ContextualPrecisionMetric"),
    ("contextual_recall", "ContextualRecallMetric"),
)

COMPARE_METRICS: tuple[str, ...] = (
    "mean_precision_at_3",
    "mean_precision_at_5",
    "mean_recall_at_10",
    "mean_mrr",
    "fact_hit_rate",
) + tuple(name for name, _ in JUDGE_METRICS)

# Grounding clause layered on top of the production persona for eval answers:
# the eval asks a single knowledge question over one context block, so the
# answer must stick to it exactly like the production knowledge path.
ANSWER_GROUNDING_INSTRUCTION = (
    "NHIỆM VỤ HÔM NAY: trả lời MỘT câu hỏi của anh/chị dựa trên các đoạn dữ "
    "liệu tuyển dụng được cung cấp trong tin nhắn. Chỉ dùng thông tin có trong "
    "các đoạn dữ liệu đó. TUYỆT ĐỐI KHÔNG BỊA ĐẶT: nếu dữ liệu không có câu "
    "trả lời, nói rõ em chưa có thông tin về vấn đề này và không bịa số liệu. "
    "Trả lời ngắn gọn, đúng trọng tâm câu hỏi."
)


# ────────────────────────── deterministic layer ──────────────────────────


def mean(values: Iterable[float | None]) -> float | None:
    """Mean of the non-None values, or None when there are none."""
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present) / len(present)


def summarize_context_positions(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize gold-chunk positions in the assembled LLM context across cases.

    Classifies each case with at least one retrieved gold chunk by its best edge
    proximity:
      * ``start`` (pos == 1): primacy edge
      * ``end``   (pos == N, N > 1): recency edge
      * ``middle`` (1 < pos < N): interior of the context
    Also reports position histograms (1-based) and the interior rate specifically
    for long contexts (``context_count > 5``).
    """
    non_abstain = [c for c in cases if not c.get("abstain")]
    position_histogram: dict[int, int] = {}
    retrieval_rank_histogram: dict[int, int] = {}
    start_cases = 0
    end_cases = 0
    middle_cases = 0
    long_context_cases = 0
    long_context_middle_cases = 0

    for c in non_abstain:
        n = int(c.get("context_count") or len(c.get("assembled_ids") or c.get("retrieved_ids") or ()))
        ranks = list(c.get("gold_retrieval_ranks") or ())
        positions = list(c.get("gold_context_positions") or ())
        for r in ranks:
            retrieval_rank_histogram[int(r)] = retrieval_rank_histogram.get(int(r), 0) + 1
        for p in positions:
            position_histogram[int(p)] = position_histogram.get(int(p), 0) + 1
        if n > 5:
            long_context_cases += 1
        if not positions:
            continue
        at_start = 1 in positions
        at_end = n > 1 and n in positions
        if at_start:
            start_cases += 1
        elif at_end:
            end_cases += 1
        else:
            middle_cases += 1
            if n > 5:
                long_context_middle_cases += 1

    total = len(non_abstain)
    edge_cases = start_cases + end_cases
    return {
        "non_abstain_cases": total,
        "long_context_cases": long_context_cases,
        "start_cases": start_cases,
        "end_cases": end_cases,
        "edge_cases": edge_cases,
        "middle_cases": middle_cases,
        "long_context_middle_cases": long_context_middle_cases,
        "edge_rate": round(edge_cases / total, 4) if total else None,
        "middle_rate": round(middle_cases / total, 4) if total else None,
        "long_context_middle_rate": (
            round(long_context_middle_cases / long_context_cases, 4)
            if long_context_cases
            else None
        ),
        "retrieval_rank_histogram": dict(sorted(retrieval_rank_histogram.items())),
        "context_position_histogram": dict(sorted(position_histogram.items())),
    }


def aggregate_case_scores(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-case score dicts into the report's ``aggregate`` block."""
    judged = [c for c in cases if c.get("judge")]
    answered = [c for c in cases if c.get("answer") is not None]
    errored = [c for c in cases if c.get("errors")]
    aggregate: dict[str, Any] = {
        "case_count": len(cases),
        "answered_cases": len(answered),
        "judged_cases": len(judged),
        "errored_cases": len(errored),
        "mean_precision_at_3": mean(c["precision_at_3"] for c in cases),
        "mean_precision_at_5": mean(c["precision_at_5"] for c in cases),
        "mean_recall_at_10": mean(c["recall_at_10"] for c in cases),
        "mean_mrr": mean(c["mrr"] for c in cases),
        "fact_hit_rate": mean(c.get("fact_hit_rate") for c in cases),
    }
    for name, _ in JUDGE_METRICS:
        aggregate[name] = mean((c.get("judge") or {}).get(name) for c in judged)
    if any("gold_context_positions" in c for c in cases):
        aggregate["context_positions"] = summarize_context_positions(cases)
    return aggregate


def build_gate_payload(report: dict[str, Any]) -> dict[str, Any] | None:
    """Reduce a report to the flat answer-quality payload for the release gate.

    Returns None when the report carries no judge scores — the gate contract
    requires all five metrics, and a payload with holes would silently pass a
    report-only gate that later turns blocking.
    """
    aggregate = report.get("aggregate") or {}
    metrics = ("fact_hit_rate",) + tuple(name for name, _ in JUDGE_METRICS)
    values: dict[str, float] = {}
    for name in metrics:
        value = aggregate.get(name)
        if value is None:
            return None
        values[name] = round(float(value), 4)
    return {
        "schema": GATE_PAYLOAD_SCHEMA,
        **values,
        "case_count": aggregate.get("case_count", 0),
        "judged_cases": aggregate.get("judged_cases", 0),
        "config": report.get("config", {}),
    }


def compare_runs(off_report: dict[str, Any], on_report: dict[str, Any]) -> dict[str, Any]:
    """P3-2 comparison: per-metric off/on/lift + the rerank decision.

    The decision reads mean precision@3 only — it is deterministic (same
    retrieval inputs, no sampling), while the LLM-judge columns carry judge +
    generation noise at this set size and are reported as evidence, not as the
    decision variable.
    """
    off_agg = off_report.get("aggregate") or {}
    on_agg = on_report.get("aggregate") or {}
    metrics: dict[str, dict[str, float]] = {}
    for name in COMPARE_METRICS:
        off_value = off_agg.get(name)
        on_value = on_agg.get(name)
        if off_value is None or on_value is None:
            continue
        metrics[name] = {
            "off": round(float(off_value), 4),
            "on": round(float(on_value), 4),
            "lift_points": round((float(on_value) - float(off_value)) * 100.0, 3),
        }
    lift = metrics.get("mean_precision_at_3", {}).get("lift_points")
    enable = lift is not None and lift >= RERANK_DECISION_PRECISION_LIFT_POINTS
    if lift is None:
        detail = "precision@3 missing from one side of the comparison; no decision"
    elif enable:
        detail = (
            f"precision@3 lift {lift:+.3f} points >= "
            f"{RERANK_DECISION_PRECISION_LIFT_POINTS} points -> enable rag_rerank_enabled"
        )
    else:
        detail = (
            f"precision@3 lift {lift:+.3f} points < "
            f"{RERANK_DECISION_PRECISION_LIFT_POINTS} points -> keep rag_rerank_enabled off"
        )
    return {
        "metrics": metrics,
        "rule": (
            "enable rag_rerank_enabled when mean precision@3 lift is >= "
            f"{RERANK_DECISION_PRECISION_LIFT_POINTS} points on the same golden answer set"
        ),
        "precision_lift_points": lift,
        "enable_rerank": enable,
        "detail": detail,
    }


def format_comparison(comparison: dict[str, Any]) -> str:
    """Human table for a :func:`compare_runs` result."""
    lines = [
        f"{'metric':<24}{'rerank=off':>12}{'rerank=on':>12}{'lift (pts)':>12}",
        "-" * 60,
    ]
    for name, row in comparison["metrics"].items():
        lines.append(
            f"{name:<24}{row['off']:>12.4f}{row['on']:>12.4f}{row['lift_points']:>+12.3f}"
        )
    lines.append("-" * 60)
    lines.append(f"decision: {comparison['detail']}")
    return "\n".join(lines)


def compare_context_orders(
    before_report: dict[str, Any], after_report: dict[str, Any]
) -> dict[str, Any]:
    """Compare ``similarity`` (before) vs ``position-aware`` (after) context assembly."""
    before_agg = before_report.get("aggregate") or {}
    after_agg = after_report.get("aggregate") or {}
    metrics: dict[str, dict[str, float]] = {}
    for name in COMPARE_METRICS:
        b_val = before_agg.get(name)
        a_val = after_agg.get(name)
        if b_val is None or a_val is None:
            continue
        metrics[name] = {
            "similarity": round(float(b_val), 4),
            "position_aware": round(float(a_val), 4),
            "lift_points": round((float(a_val) - float(b_val)) * 100.0, 3),
        }
    before_pos = before_agg.get("context_positions") or {}
    after_pos = after_agg.get("context_positions") or {}
    return {
        "metrics": metrics,
        "before_positions": before_pos,
        "after_positions": after_pos,
    }


def format_context_order_comparison(comparison: dict[str, Any]) -> str:
    """Human table for a :func:`compare_context_orders` result."""
    lines = [
        f"{'metric':<24}{'similarity':>14}{'position-aware':>16}{'lift (pts)':>12}",
        "-" * 66,
    ]
    for name, row in comparison["metrics"].items():
        lines.append(
            f"{name:<24}{row['similarity']:>14.4f}{row['position_aware']:>16.4f}{row['lift_points']:>+12.3f}"
        )
    b_pos = comparison.get("before_positions") or {}
    a_pos = comparison.get("after_positions") or {}
    if b_pos and a_pos:
        lines.append("-" * 66)
        for key in ("edge_rate", "middle_rate", "long_context_middle_rate"):
            bv = b_pos.get(key)
            av = a_pos.get(key)
            if bv is not None and av is not None:
                lift = (float(av) - float(bv)) * 100.0
                lines.append(f"{key:<24}{float(bv):>14.4f}{float(av):>16.4f}{lift:>+12.3f}")
    return "\n".join(lines)


# ─────────────────────────── pipeline layers ────────────────────────────


@dataclass(frozen=True)
class GoldBundle:
    """Answer-gold entries joined with their rag_gold retrieval cases."""

    entries: tuple  # tuple[AnswerGold, ...]
    cases_by_id: dict[str, Any]  # rag_gold GoldCase keyed by id
    chunks: tuple
    embeddings: dict[str, list[float]]


def load_gold_bundle(embeddings_path: Path | None = None) -> GoldBundle:
    """Load the golden answer set + the rag_gold fixtures it references."""
    from tests.golden.answers import load_answer_gold
    from tests.rag_gold.loader import load_cases, load_chunks, load_embeddings

    entries = load_answer_gold()
    cases_by_id = {case.id: case for case in load_cases()}
    embeddings = (
        load_embeddings(embeddings_path)
        if embeddings_path is not None
        else load_embeddings()
    )
    return GoldBundle(
        entries=entries,
        cases_by_id=cases_by_id,
        chunks=load_chunks(),
        embeddings=embeddings,
    )


def validate_bundle(bundle: GoldBundle) -> None:
    """Fail fast on dangling refs — every entry must resolve to a gold case."""
    missing = [e.id for e in bundle.entries if e.ref not in bundle.cases_by_id]
    if missing:
        raise ValueError(f"answer-gold entries reference unknown rag_gold cases: {missing}")
    mismatched = [
        e.id
        for e in bundle.entries
        if bundle.cases_by_id[e.ref].query != e.question
    ]
    if mismatched:
        raise ValueError(f"answer-gold question drift from rag_gold query: {mismatched}")


@contextmanager
def rerank_flag(enabled: bool):
    """Flip ``rag_rerank_enabled`` for the duration of the block.

    Reads/writes the cached Settings singleton — the same runtime knob
    ``rerank_if_enabled`` consults, so the eval exercises the production
    flag path exactly (including its disabled identity passthrough).
    """
    from app.core.config import get_settings

    settings = get_settings()
    previous = settings.rag_rerank_enabled
    settings.rag_rerank_enabled = enabled
    try:
        yield
    finally:
        settings.rag_rerank_enabled = previous


def retrieve_contexts(
    bundle: GoldBundle, ref: str, *, top_k: int, rerank_enabled: bool
) -> tuple[list[str], list[str]]:
    """Run the real post-retrieval pipeline for one gold case.

    Returns (contexts, retrieved_ids) in ranked order. Uses
    ``tests.services_runner.build_rows_for_case`` — production
    ``rerank_if_enabled`` over fixture rows with canned embeddings.
    """
    from tests.services_runner import build_rows_for_case

    case = bundle.cases_by_id[ref]
    with rerank_flag(rerank_enabled):
        rows = build_rows_for_case(case, bundle.chunks, bundle.embeddings, top_k=top_k)
    retrieved_ids = [row.id for row in rows]
    contexts = [row.content for row in rows]
    return contexts, retrieved_ids


_ANSWER_SYSTEM_SUFFIX = "\n\n" + ANSWER_GROUNDING_INSTRUCTION


def _message_text(message: Any) -> str:
    """Best-effort plain text from a chat message (content may be blocks)."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [str(block.get("text", "")) if isinstance(block, dict) else str(block) for block in content]
        return "\n".join(p for p in parts if p).strip()
    return str(content).strip()


def build_agent_chat():
    """The app's production agent-role chat client (settings-backed provider)."""
    from app.graph.prompts import AGENT_SYSTEM_PROMPT
    from app.graph.providers import _chat_for_role

    model = _chat_for_role("agent", temperature=0.0)
    return model, AGENT_SYSTEM_PROMPT


def _generate_answer_with(
    model: Any, persona: str, question: str, contexts: list[str]
) -> str:
    """Grounded answer over ``contexts`` under the production persona."""
    from langchain_core.messages import HumanMessage, SystemMessage

    context_block = "\n\n".join(f"[Đoạn {i + 1}]\n{c}" for i, c in enumerate(contexts))
    reply = model.invoke(
        [
            SystemMessage(content=persona + _ANSWER_SYSTEM_SUFFIX),
            HumanMessage(content=f"Dữ liệu tuyển dụng:\n{context_block}\n\nCâu hỏi: {question}"),
        ]
    )
    return _message_text(reply)


def generate_answer(question: str, contexts: list[str]) -> str:
    """One-shot grounded answer (builds the provider client per call)."""
    model, persona = build_agent_chat()
    return _generate_answer_with(model, persona, question, contexts)


class AppProviderJudge:
    """DeepEval judge backed by the app's own provider (no new API keys).

    Duck-typed against ``deepeval.models.DeepEvalBaseLLM`` and subclassed at
    first use so importing this module never requires deepeval. The base class
    calls ``load_model()`` from ``__init__``; here that builds the same
    agent-role chat client the answer pipeline uses, at temperature 0.
    """

    def __init__(self) -> None:
        from deepeval.models import DeepEvalBaseLLM

        class _Judge(DeepEvalBaseLLM):
            def load_model(self):  # noqa: ANN202
                model, _ = build_agent_chat()
                return model

            def get_model_name(self) -> str:
                return self.name or "app-provider"

            def generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
                from langchain_core.messages import HumanMessage

                return _message_text(self.model.invoke([HumanMessage(content=str(prompt))]))

            async def a_generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
                from langchain_core.messages import HumanMessage

                reply = await self.model.ainvoke([HumanMessage(content=str(prompt))])
                return _message_text(reply)

        self._judge = _Judge("app-provider")

    @property
    def model_name(self) -> str:
        return self._judge.get_model_name()

    def measure(self, question: str, answer: str, contexts: list[str], reference: str) -> dict[str, Any]:
        """Score one case with the four judge metrics; per-metric errors are returned."""
        from deepeval.metrics import (
            AnswerRelevancyMetric,
            ContextualPrecisionMetric,
            ContextualRecallMetric,
            FaithfulnessMetric,
        )
        from deepeval.test_case import LLMTestCase

        metric_classes = {
            "faithfulness": FaithfulnessMetric,
            "answer_relevancy": AnswerRelevancyMetric,
            "contextual_precision": ContextualPrecisionMetric,
            "contextual_recall": ContextualRecallMetric,
        }
        test_case = LLMTestCase(
            input=question,
            actual_output=answer,
            expected_output=reference,
            retrieval_context=contexts or [""],
        )
        scores: dict[str, float | None] = {}
        reasons: dict[str, str] = {}
        errors: dict[str, str] = {}
        for name, _ in JUDGE_METRICS:
            metric = metric_classes[name](
                threshold=0.5,
                model=self._judge,
                eval_mode="llm",
                include_reason=True,
                async_mode=False,
                verbose_mode=False,
            )
            try:
                metric.measure(test_case, _show_indicator=False)
                scores[name] = float(metric.score)
                reasons[name] = str(getattr(metric, "reason", "") or "")
            except Exception as exc:  # noqa: BLE001 — a judge failure must not kill the run
                scores[name] = None
                errors[name] = f"{type(exc).__name__}: {exc}"
        return {"scores": scores, "reasons": reasons, "errors": errors}


# ───────────────────────────── run + CLI ────────────────────────────────


def run_case(
    bundle: GoldBundle,
    gold,
    *,
    top_k: int,
    rerank_enabled: bool,
    answers_mode: str,
    replay_answers: dict[str, Any] | None,
    judge: AppProviderJudge | None,
    generate: Callable[[str, list[str]], str] | None,
    context_order: str | None = None,
) -> dict[str, Any]:
    """Score one entry end-to-end; never raises — errors land in the case dict."""
    from app.graph.tools.knowledge import order_context_chunks, resolve_context_order
    from tests.golden.answers import fact_hit_rate
    from tests.rag_gold.precision import score_case

    resolved_order = resolve_context_order(context_order)
    case: dict[str, Any] = {
        "id": gold.id,
        "ref": gold.ref,
        "category": gold.category,
        "abstain": gold.abstain,
        "question": gold.question,
        "context_order": resolved_order,
        "errors": [],
    }
    contexts, retrieved_ids = retrieve_contexts(
        bundle, gold.ref, top_k=top_k, rerank_enabled=rerank_enabled
    )
    gold_case = bundle.cases_by_id[gold.ref]
    expected_set = set(gold_case.expected_chunk_ids)
    scored = score_case(
        case_id=gold.id,
        retrieved=retrieved_ids,
        expected=expected_set,
        bait=gold_case.bait,
    )
    assembled_ids = order_context_chunks(retrieved_ids, order=resolved_order)
    assembled_contexts = order_context_chunks(contexts, order=resolved_order)
    gold_retrieval_ranks = [
        idx + 1 for idx, cid in enumerate(retrieved_ids) if cid in expected_set
    ]
    gold_context_positions = [
        idx + 1 for idx, cid in enumerate(assembled_ids) if cid in expected_set
    ]
    case.update(
        {
            "retrieved_ids": retrieved_ids,
            "assembled_ids": assembled_ids,
            "expected_chunk_ids": sorted(gold_case.expected_chunk_ids),
            "context_count": len(assembled_ids),
            "gold_retrieval_ranks": gold_retrieval_ranks,
            "gold_context_positions": gold_context_positions,
            "contexts": contexts,
            "assembled_contexts": assembled_contexts,
            "precision_at_3": scored.precision_at_3,
            "precision_at_5": scored.precision_at_5,
            "recall_at_10": scored.recall_at_10,
            "mrr": scored.mrr,
        }
    )

    answer: str | None = None
    if answers_mode == "replay":
        recorded = (replay_answers or {}).get(gold.id)
        if recorded is None:
            case["errors"].append("replay: no recorded answer for this id")
        else:
            answer = str(recorded)
    elif answers_mode == "live":
        assert generate is not None
        try:
            answer = generate(gold.question, assembled_contexts)
        except Exception as exc:  # noqa: BLE001 — report, don't abort the run
            case["errors"].append(f"generation: {type(exc).__name__}: {exc}")
    case["answer"] = answer
    case["fact_hit_rate"] = None if answer is None else fact_hit_rate(answer, gold)

    case["judge"] = None
    case["judge_reasons"] = {}
    if judge is not None and answer is not None:
        try:
            result = judge.measure(gold.question, answer, contexts, gold.reference_answer())
        except Exception as exc:  # noqa: BLE001
            case["errors"].append(f"judge: {type(exc).__name__}: {exc}")
        else:
            scores = result["scores"]
            case["judge"] = {k: v for k, v in scores.items() if v is not None}
            case["judge_reasons"] = result["reasons"]
            for name, err in result["errors"].items():
                case["errors"].append(f"judge.{name}: {err}")
    return case


def run_config(
    bundle: GoldBundle,
    *,
    rerank_enabled: bool,
    top_k: int,
    answers_mode: str,
    replay_answers: dict[str, Any] | None,
    judge: Any | None,
    generate: Callable[[str, list[str]], str] | None,
    answer_model: str | None,
    judge_model: str | None,
    max_cases: int | None,
    concurrency: int,
    context_order: str | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Score the whole golden answer set under one rerank/context-order configuration."""
    from app.graph.tools.knowledge import resolve_context_order

    resolved_order = resolve_context_order(context_order)
    entries = list(bundle.entries)
    if max_cases is not None:
        entries = entries[:max_cases]
    if not entries:
        raise ValueError("no answer-gold entries to evaluate")

    started = perf_counter()
    llm_bound = generate is not None or judge is not None
    case_args = [
        dict(
            bundle=bundle,
            gold=gold,
            top_k=top_k,
            rerank_enabled=rerank_enabled,
            answers_mode=answers_mode,
            replay_answers=replay_answers,
            judge=judge,
            generate=generate,
            context_order=resolved_order,
        )
        for gold in entries
    ]
    if llm_bound and concurrency > 1:
        results: list[dict[str, Any] | None] = [None] * len(case_args)
        done = 0
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(run_case, **kwargs): i for i, kwargs in enumerate(case_args)}
            for future in as_completed(futures):
                results[futures[future]] = future.result()
                done += 1
                if done % 5 == 0 or done == len(case_args):
                    log(
                        f"  [{done}/{len(case_args)}] cases scored "
                        f"(rerank={rerank_enabled}, order={resolved_order})"
                    )
        cases = [r for r in results if r is not None]
    else:
        cases = []
        for i, kwargs in enumerate(case_args, start=1):
            cases.append(run_case(**kwargs))
            if i % 5 == 0 or i == len(case_args):
                log(
                    f"  [{i}/{len(case_args)}] cases scored "
                    f"(rerank={rerank_enabled}, order={resolved_order})"
                )

    report = {
        "schema": REPORT_SCHEMA,
        "config": {
            "rag_rerank_enabled": rerank_enabled,
            "rag_context_order": resolved_order,
            "top_k": top_k,
            "answers": answers_mode,
            "judge": judge is not None,
            "judge_model": judge_model,
            "answer_model": answer_model,
            "entry_count": len(entries),
            "elapsed_seconds": round(perf_counter() - started, 1),
        },
        "cases": cases,
        "aggregate": aggregate_case_scores(cases),
    }
    return report


def _summary_lines(report: dict[str, Any]) -> list[str]:
    agg = report["aggregate"]
    cfg = report["config"]
    lines = [
        f"rerank={cfg['rag_rerank_enabled']} answers={cfg['answers']} judge={cfg['judge']} "
        f"cases={agg['case_count']} judged={agg['judged_cases']} errored={agg['errored_cases']}"
    ]
    for name in COMPARE_METRICS:
        value = agg.get(name)
        if value is not None:
            lines.append(f"  {name:<24}{value:.4f}")
    return lines


def _resolve_answers_mode(args: argparse.Namespace) -> str:
    if args.answers != "auto":
        return args.answers
    if args.no_answers:
        return "none"
    return "replay" if args.replay is not None else "live"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rerank", choices=("off", "on", "both"), default="both")
    parser.add_argument(
        "--context-order",
        choices=("auto", "similarity", "position-aware", "both"),
        default="auto",
        help="Context chunk ordering mode (default: Settings.rag_context_order)",
    )
    parser.add_argument(
        "--embeddings",
        type=Path,
        default=None,
        help="Optional path to canned embeddings fixture (default: rag_gold/embeddings.json)",
    )
    parser.add_argument("--judge", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--answers", choices=("auto", "live", "replay", "none"), default="auto")
    parser.add_argument("--replay", type=Path, help="Prior report JSON supplying recorded answers")
    parser.add_argument("--no-answers", action="store_true", help="Retrieval metrics only")
    parser.add_argument("--top-k", type=int, default=25)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output", type=Path, help="Write the report/comparison JSON here")
    parser.add_argument(
        "--gate-output",
        type=Path,
        help="Write the flat answer-quality payload for scripts/release_gate_check.py",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    answers_mode = _resolve_answers_mode(args)
    if answers_mode == "replay" and args.replay is None:
        parser.error("--answers replay requires --replay REPORT")
    if answers_mode == "live" and args.no_answers:
        parser.error("--no-answers conflicts with --answers live")

    bundle = load_gold_bundle(args.embeddings)
    validate_bundle(bundle)

    replay_answers: dict[str, Any] | None = None
    if answers_mode == "replay":
        replay_report = json.loads(Path(args.replay).read_text(encoding="utf-8"))
        if replay_report.get("schema") != REPORT_SCHEMA:
            parser.error(f"--replay must point at a {REPORT_SCHEMA} file")
        replay_answers = {c["id"]: c.get("answer") for c in replay_report.get("cases", [])}

    # Resolve the LLM layers up front: a missing provider fails before any
    # retrieval work, and --judge auto degrades to deterministic-only.
    generate: Callable[[str, list[str]], str] | None = None
    answer_model: str | None = None
    judge: Any | None = None
    judge_model: str | None = None
    provider_error: Exception | None = None
    needs_provider = answers_mode == "live" or (args.judge != "off" and answers_mode != "none")
    if needs_provider:
        try:
            model, persona = build_agent_chat()
            answer_model = str(getattr(model, "model_name", None) or "app-provider")
        except Exception as exc:  # noqa: BLE001
            provider_error = exc
            if answers_mode == "live":
                print(
                    f"error: live answer generation needs the app provider: {exc}\n"
                    "hint: configure the provider in backend/.env, or rescore a prior "
                    "run offline with --replay REPORT --judge off",
                    file=sys.stderr,
                )
                return 2
        else:
            if answers_mode == "live":
                generate = lambda q, ctx: _generate_answer_with(model, persona, q, ctx)  # noqa: E731

    if args.judge != "off" and answers_mode != "none":
        if provider_error is None:
            try:
                judge = AppProviderJudge()
                judge_model = judge.model_name
            except Exception as exc:  # noqa: BLE001
                provider_error = exc
                judge = None
        if judge is None and args.judge == "on":
            print(f"error: --judge on but the DeepEval judge is unavailable: {provider_error}", file=sys.stderr)
            return 2
        if judge is None:
            print(f"note: judge skipped — deterministic metrics only ({provider_error})")

    from app.core.config import get_settings
    from app.graph.tools.knowledge import resolve_context_order

    if args.context_order == "both":
        rerank_enabled = args.rerank == "on"
        order_reports: dict[str, dict[str, Any]] = {}
        for order_mode in ("similarity", "position-aware"):
            print(f"== eval run: rag_context_order={order_mode} (rerank={rerank_enabled}) ==")
            order_reports[order_mode] = run_config(
                bundle,
                rerank_enabled=rerank_enabled,
                top_k=args.top_k,
                answers_mode=answers_mode,
                replay_answers=replay_answers,
                judge=judge,
                generate=generate,
                answer_model=answer_model,
                judge_model=judge_model,
                max_cases=args.max_cases,
                concurrency=args.concurrency,
                context_order=order_mode,
            )
            for line in _summary_lines(order_reports[order_mode]):
                print(line)
        comparison = compare_context_orders(
            order_reports["similarity"], order_reports["position-aware"]
        )
        print()
        print(format_context_order_comparison(comparison))
        payload: dict[str, Any] = {
            "schema": COMPARISON_SCHEMA,
            "similarity": order_reports["similarity"],
            "position_aware": order_reports["position-aware"],
            "comparison": comparison,
        }
        gate_source = order_reports["position-aware"]
    else:
        resolved_order = (
            resolve_context_order()
            if args.context_order == "auto"
            else resolve_context_order(args.context_order)
        )
        shipped_rerank = get_settings().rag_rerank_enabled
        configs = [False, True] if args.rerank == "both" else [args.rerank == "on"]
        reports: dict[str, dict[str, Any]] = {}
        for rerank_enabled in configs:
            label = "on" if rerank_enabled else "off"
            print(f"== eval run: rag_rerank_enabled={label} ==")
            reports[label] = run_config(
                bundle,
                rerank_enabled=rerank_enabled,
                top_k=args.top_k,
                answers_mode=answers_mode,
                replay_answers=replay_answers,
                judge=judge,
                generate=generate,
                answer_model=answer_model,
                judge_model=judge_model,
                max_cases=args.max_cases,
                concurrency=args.concurrency,
                context_order=resolved_order,
            )
            for line in _summary_lines(reports[label]):
                print(line)

        if args.rerank == "both":
            comparison = compare_runs(reports["off"], reports["on"])
            print()
            print(format_comparison(comparison))
            payload = {
                "schema": COMPARISON_SCHEMA,
                "off": reports["off"],
                "on": reports["on"],
                "comparison": comparison,
            }
            gate_source = reports["on"] if shipped_rerank else reports["off"]
        else:
            payload = reports["on" if args.rerank == "on" else "off"]
            gate_source = payload

    if args.output is not None:
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report written: {args.output}")

    if args.gate_output is not None:
        gate_payload = build_gate_payload(gate_source)
        if gate_payload is None:
            print(
                "gate-output skipped: judge metrics unavailable — the release-gate "
                "payload requires all five answer-quality scores",
                file=sys.stderr,
            )
        else:
            args.gate_output.write_text(
                json.dumps(gate_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"gate payload written: {args.gate_output}")

    agg = gate_source["aggregate"]
    if agg["case_count"] and agg["errored_cases"] == agg["case_count"]:
        print("error: every case errored", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
