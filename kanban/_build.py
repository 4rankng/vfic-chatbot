"""Render the tech-debt audit backlog into kanban/ as one markdown ticket per file.

Run:  python3 kanban/_build.py
Source of truth: the ticket data modules next to this file (tickets_*.py).
Idempotent: rewrites ticket files and README.md from the data.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import tickets_a
import tickets_b
import tickets_c
import tickets_d

ROOT = Path(__file__).resolve().parent

SEV_ORDER = ["critical", "high", "medium", "low"]
SEV_COLUMN = {
    "critical": ("P0", "Critical — production or data loss risk"),
    "high": ("P1", "High — serious risk, schedule next"),
    "medium": ("P2", "Medium — real debt, plan it"),
    "low": ("P3", "Low — hardening / cleanup"),
}
AREA_TITLE = {
    "security": "Security",
    "reliability": "Reliability",
    "performance": "Performance",
    "architecture": "Architecture & dead code",
    "frontend": "Frontend",
    "testing": "Testing & CI",
    "ops": "Ops, deploy & data",
    "docs": "Docs & repo hygiene",
}


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:64].rstrip("-")


def tickets():
    out = []
    for mod in (tickets_a, tickets_b, tickets_c, tickets_d):
        out.extend(mod.TICKETS)
    seen = set()
    for t in out:
        assert t["id"] not in seen, f"duplicate id {t['id']}"
        seen.add(t["id"])
    out.sort(key=lambda t: (SEV_ORDER.index(t["sev"]), t["id"]))
    return out


def withdrawn():
    """Ids that were allocated then withdrawn; rendered next to the deferred section."""
    out = []
    for mod in (tickets_a, tickets_b, tickets_c, tickets_d):
        out.extend(getattr(mod, "WITHDRAWN", []))
    return out


def _existing_status(path: Path) -> str | None:
    """Read the progress marker already recorded in a rendered ticket file.

    ``status`` is mutable progress state, not audit data, and it is only ever
    advanced by hand in the ticket file. Rebuilding must not silently reset a
    ticket to ``todo``, so the renderer carries the on-disk value forward unless
    the ticket data declares an explicit ``status``.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    match = re.search(r"^status: (\w+)$", text, re.MULTILINE)
    return match.group(1) if match else None


def render_ticket(t, status: str) -> str:
    lines = [
        "---",
        f"id: {t['id']}",
        f"title: {json.dumps(t['title'], ensure_ascii=False)}",
        f"severity: {t['sev']}",
        f"area: {t['area']}",
        f"labels: [{', '.join(t['labels'])}]",
        f"effort: {t['effort']}",
        f"status: {status}",
        "found: 2026-09-24",
        "---",
        "",
        f"# {t['id']} — {t['title']}",
        "",
        f"**Severity:** {t['sev']} · **Area:** {t['area']} · **Effort:** {t['effort']} · "
        f"**Labels:** {', '.join(t['labels'])}",
        "",
        "## Problem",
        "",
        t["problem"],
        "",
        "## Evidence",
        "",
    ]
    lines += [f"- {e}" for e in t["evidence"]]
    lines += ["", "## Impact", "", t["impact"], "", "## Suggested fix", "", t["fix"], ""]
    if t.get("notes"):
        lines += ["## Notes", "", t["notes"], ""]
    lines += [
        "---",
        "",
        "_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). "
        "No code was changed by the audit; all claims are grounded in the cited "
        "`path:line` locations._",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ts = tickets()
    for t in ts:
        path = ROOT / f"{t['id']}-{slugify(t['title'])}.md"
        status = t.get("status") or _existing_status(path) or "todo"
        path.write_text(render_ticket(t, status), encoding="utf-8")

    by_sev: dict[str, list] = {s: [] for s in SEV_ORDER}
    for t in ts:
        by_sev[t["sev"]].append(t)

    counts = " · ".join(f"{SEV_COLUMN[s][0]} {len(by_sev[s])}" for s in SEV_ORDER)
    out = [
        "# Tech-debt kanban",
        "",
        "Backlog from the read-only codebase audit of **2026-09-24** (HEAD `923b1d3f`, "
        "`main`). One file per ticket. Nothing here has been implemented.",
        "",
        f"**Board:** {counts} · **Total {len(ts)}**",
        "",
        "## How to use",
        "",
        "- Each ticket is self-contained: problem, `path:line` evidence, impact, and a "
        "concrete fix with an effort estimate (S ≈ hours, M ≈ a day, L ≈ multi-day).",
        "- Ticket front-matter carries `severity`, `area`, `labels`, `effort`, `status`. "
        "Move `status` through `todo` → `doing` → `done` as work proceeds.",
        "- `status` is progress state and survives regeneration: the renderer carries the "
        "value already in the ticket file forward, so rebuilding never resets a ticket to "
        "`todo`. Add a `status` key to the ticket data only to force an initial value.",
        "- Several tickets are coupled by design; the `Notes` section names the ticket "
        "that must land first or alongside.",
        "- Regenerate from data with `python3 kanban/_build.py` after editing the "
        "`tickets_*.py` modules (they are the source of truth for the board).",
        "",
        "## Health snapshot at audit time",
        "",
        "| Signal | Result |",
        "|---|---|",
        "| Backend unit suite | `2243 passed, 42 skipped, 88 deselected` in 23.4 s |",
        "| Backend `ruff check .` | clean |",
        "| Frontend `tsc --noEmit` | clean |",
        "| Backend integration suite in CI | 1 of 29 files |",
        "| Frontend coverage gate | 3 of 425 files |",
        "| Backend coverage measurement | none |",
        "| Tracked repo artifacts | `assets/showoff` ~21.5 MB, `repomix-output.xml` 4.8 MB |",
        "| Dev vs prod Python | 3.14.5 vs `python:3.12-slim` |",
        "",
        "The tree is lint-clean and type-clean, so the debt below is structural, "
        "not stylistic.",
        "",
    ]
    for sev in SEV_ORDER:
        if not by_sev[sev]:
            continue
        code, label = SEV_COLUMN[sev]
        out += [f"## {code} — {label} ({len(by_sev[sev])})", "", "| ID | Title | Area | Effort |", "|---|---|---|---|"]
        for t in by_sev[sev]:
            fname = f"{t['id']}-{slugify(t['title'])}.md"
            out.append(f"| [{t['id']}]({fname}) | {t['title']} | {t['area']} | {t['effort']} |")
        out.append("")

    out += ["## By area", "", "| Area | Critical | High | Medium | Low | Total |", "|---|---|---|---|---|---|"]
    for area in AREA_TITLE:
        row = [t for t in ts if t["area"] == area]
        if not row:
            continue
        out.append(
            "| {} | {} | {} | {} | {} | {} |".format(
                AREA_TITLE[area],
                *[sum(1 for t in row if t["sev"] == s) for s in SEV_ORDER],
                len(row),
            )
        )
    out += [
        "",
        "Counts here derive from each ticket's single `area` field, not from `labels`, which "
        "may carry cross-cutting areas — e.g. SEC-02 and SEC-05 sit in the Security row but "
        "are also labeled `reliability`, so a label-based Reliability count reads "
        f"{sum(1 for t in ts if 'reliability' in t['labels'])}, not "
        f"{sum(1 for t in ts if t['area'] == 'reliability')}.",
        "",
        "## Suggested first wave",
        "",
        "Ordered by risk-per-hour, not by severity label:",
        "",
        "1. **SEC-02** — thread the viewer through the lead by-id routes; one file, "
        "closes whole-tenant candidate-PII exposure.",
        "2. **OPS-01 / OPS-02 / OPS-03** — the disaster-recovery path is non-functional "
        "and the credential encryption key is not backed up.",
        "3. **PERF-02** — a Redis eviction policy that can silently suppress every turn.",
        "4. **TEST-01** — widen the CI integration lane from 1 file to 29; the "
        "invariants are already written and currently unenforced.",
        "5. **REL-01** — a partial multi-bubble delivery that makes the bot answer the "
        "candidate twice.",
        "",
        "## Deferred by request",
        "",
        "Findings the audit confirmed but which are **deliberately not ticketed yet**. "
        "Recorded here so they are not lost or re-discovered from scratch.",
        "",
        "**Unauthenticated Zalo OA webhook.** `POST /webhooks/zalo/oa` "
        "(`backend/app/api/webhooks.py:148-188`) performs no authentication of any kind — "
        "signature verification was deliberately disabled because the stored credential is "
        "the wrong Zalo secret (`backend/app/api/webhooks.py:171-176`). Any unauthenticated "
        "caller can create conversations, create and update leads, and enqueue real LLM "
        "turns: dedup is per `(sender, msg_id)`, so looping fresh sender ids yields "
        "unbounded cost against `llm_concurrency_limit = 8` on a 2 vCPU box. It is the only "
        "credential-free state-changing endpoint in the application.",
        "",
        "Root cause: the app holds the OA *access-token* secret rather than Zalo's webhook "
        "checksum key, so the (correct) verifier at "
        "`backend/app/services/zalo_oa_signature.py:verify_signature` could never pass. "
        "Fixing the code without fixing the credential would false-reject 100% of real "
        "events. Either obtain the checksum key and wire the verifier into the inbound "
        "route, or delete the route if the OA channel is not in production use.",
        "",
        "### Withdrawn ticket ids",
        "",
        "The id sequence is deliberately **not** contiguous: the finding above was "
        "allocated an id, then withdrawn by request before the board was published, and "
        "no id is renumbered. The gap SEC-02…SEC-08 is intentional — no ticket is "
        "missing or lost.",
        "",
        *[
            f"- **{w['id']} (withdrawn)** — {w['title']} — deferred by request, not "
            f"counted on the board. {w['reason']}"
            for w in withdrawn()
        ],
        "",
        "## Not tickets",
        "",
        "Findings the audit deliberately records as *not* defects, so they are not "
        "re-litigated:",
        "",
        "- The layering rules (`API → Services → Models/Core`, `graph/` behind "
        "`graph/ports.py`) are machine-enforced with a zero-entry allowlist and are "
        "not violated.",
        "- The pre-send ownership claim (`claim_send`) is genuinely atomic; the outbox "
        "claim cannot double-send.",
        "- Raw SQL is static or whitelist-built; no SQL injection, XXE, path traversal, "
        "or SSRF was found.",
        "- No hardcoded secrets; `backend/.env` is untracked and ignored; credential-"
        "bearing transport loggers are silenced.",
        "- Socket.IO enforces per-room authorization on connect and on every join.",
        "- `assets/showoff`, `openwiki/`, and `kb/` are tracked but were classified as "
        "artifacts by other ignore files — the fix is a `.gitignore` rule, not a rewrite.",
        "",
    ]

    (ROOT / "README.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {len(ts)} tickets + README.md")
    for sev in SEV_ORDER:
        print(f"  {sev}: {len(by_sev[sev])}")


if __name__ == "__main__":
    main()
