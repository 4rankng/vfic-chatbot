"""Render the tech-debt audit backlog into the kanban board.

Board layout follows the house kanban convention (see the `kanban-work` practice):

    kanban/
      TODO/            waiting
      IN_PROGRESS/     claimed, being implemented
      DEV_COMPLETED/   local criteria evidenced
      QA_TESTED/       verified locally end to end

`kanban/` is exactly those four column folders — no index, no sidecars. This
generator and its data modules live OUTSIDE the board, under `scripts/kanban/`.

Cards are markdown, named `YYYYMMDD_<ID>-<slug>.md` (date prefix + the stable
ticket id + a kebab-case slug). The id is kept in the filename because the cards
cross-reference each other by id.

Run:  python3 scripts/kanban/build.py
Idempotent: rewrites every card from the data modules, so the data is the source
of truth for content and column. A card's true column is whatever the data says;
move a card by editing its `column` in the data module, not by hand.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
KANBAN = REPO_ROOT / "kanban"

sys.path.insert(0, str(HERE))

import tickets_a  # noqa: E402
import tickets_b  # noqa: E402
import tickets_c  # noqa: E402
import tickets_d  # noqa: E402

TICKET_DATE = "20260924"
COLUMNS = ["TODO", "IN_PROGRESS", "DEV_COMPLETED", "QA_TESTED"]
COLUMN_STATUS = {
    "TODO": "todo",
    "IN_PROGRESS": "doing",
    "DEV_COMPLETED": "dev-completed",
    "QA_TESTED": "qa-tested",
}

SEV_ORDER = ["critical", "high", "medium", "low"]
SEV_LABEL = {
    "critical": "P0",
    "high": "P1",
    "medium": "P2",
    "low": "P3",
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
        col = t.get("column", "TODO")
        assert col in COLUMNS, f"{t['id']}: bad column {col}"
    out.sort(key=lambda t: (SEV_ORDER.index(t["sev"]), t["id"]))
    return out


def card_name(t) -> str:
    return f"{TICKET_DATE}_{t['id']}-{slugify(t['title'])}.md"


def render_card(t) -> str:
    col = t.get("column", "TODO")
    lines = [
        "---",
        f"id: {t['id']}",
        f"title: {json.dumps(t['title'], ensure_ascii=False)}",
        f"severity: {t['sev']}",
        f"area: {t['area']}",
        f"labels: [{', '.join(t['labels'])}]",
        f"effort: {t['effort']}",
        f"status: {COLUMN_STATUS[col]}",
        f"column: {col}",
        f"opened: {TICKET_DATE[:4]}-{TICKET_DATE[4:6]}-{TICKET_DATE[6:]}",
        "---",
        "",
        f"# {t['id']} — {t['title']}",
        "",
        f"**Severity:** {t['sev']} · **Area:** {t['area']} · **Effort:** {t['effort']} · "
        f"**Labels:** {', '.join(t['labels'])}",
        "",
        f"**Trạng thái:** {col}",
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
    if t.get("evidence_log"):
        lines += ["## Evidence log", ""] + [f"- {e}" for e in t["evidence_log"]] + [""]
    lines += [
        "---",
        "",
        f"_Opened {TICKET_DATE[:4]}-{TICKET_DATE[4:6]}-{TICKET_DATE[6:]} from the read-only "
        "tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is "
        "grounded in the cited `path:line` locations._",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ts = tickets()

    for col in COLUMNS:
        (KANBAN / col).mkdir(parents=True, exist_ok=True)
        # Regeneration is authoritative: clear the column so renames/moves cannot
        # leave a stale duplicate behind.
        for stale in (KANBAN / col).glob("*.md"):
            stale.unlink()

    by_col: dict[str, list] = {c: [] for c in COLUMNS}
    for t in ts:
        col = t.get("column", "TODO")
        (KANBAN / col / card_name(t)).write_text(render_card(t), encoding="utf-8")
        by_col[col].append(t)

    print(f"wrote {len(ts)} cards into {KANBAN}")
    for col in COLUMNS:
        print(f"  {col}: {len(by_col[col])}")

    total = len(ts)
    by_sev = {s: sum(1 for t in ts if t["sev"] == s) for s in SEV_ORDER}
    done = len(by_col["DEV_COMPLETED"]) + len(by_col["QA_TESTED"])
    print(
        "  severity: "
        + " · ".join(f"{SEV_LABEL[s]} {by_sev[s]}" for s in SEV_ORDER)
        + f" · closed {done}/{total}"
    )


if __name__ == "__main__":
    main()
