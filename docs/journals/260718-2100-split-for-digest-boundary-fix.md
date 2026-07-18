---
title: split_for_digest boundary-aware chunking fix
date: 2026-07-18
session: split-for-digest-boundary-fix
---

# split_for_digest boundary-aware chunking fix

## Context

A chunking audit of the knowledge digest pipeline surfaced four verified defects
in `backend/app/services/knowledge/extraction.py::split_for_digest`. Despite a
docstring claiming "paragraph boundaries are respected," the code did a raw
`text[start:start+max_chars]` slice — which corrupted Vietnamese diacritics and
CJK sequences at the seam, produced near-duplicate final chunks via off-by-one
tail handling, and silently dropped content past the `DIGEST_MAX_SECTIONS = 20`
cap with no signal anywhere. The single regression test used `"x" * 15000`,
which could not expose any of these defects. Plan: `plans/260718-2100-...`.

## What Happened

The splitter was rewritten to snap cuts to paragraph → sentence → word → hard
cut (in that priority order), with explicit sliding-window math that never
duplicates the tail. The function now returns a `DigestSections` dataclass
(`sections`, `truncated`, `dropped_chars`, `total_chars`) so the pipeline can
surface truncation in `digest_meta` and log a warning instead of failing
silently. The magic `400` overlap became `DIGEST_SECTION_OVERLAP` in
`config.py`. Six regression tests cover each defect: paragraph snap, sentence
snap, tail-not-duplicated, truncation, Vietnamese diacritics, CJK.

The mandatory `code-reviewer` pass came back GO but flagged a real Medium:
the CJK test passed only by coincidence — the 12-char sentence divided 6000
evenly, hiding the fact that `_SENTENCE_BOUNDARY_RE = (?<=[.!?。！？])\s+`
requires trailing whitespace, so general CJK prose (no inter-sentence space)
fell through to a hard cut. That was the "test green, claim false" pattern.
The fix was to split the regex into a Latin-sentence pattern (needs trailing
space) and a dedicated CJK-sentence pattern that snaps after the terminator
itself. The CJK test was also rewritten to use a 9-char sentence (6000 % 9 = 6,
forcing a mid-sentence naive cut) so the test actually proves the fix.

## Reflection

The CJK slip is the lesson. The original test was technically green and the
function was technically correct for the input the test provided — but the
*claim* the test was meant to enforce (CJK snaps on the terminator) was not
actually exercised. Pairing the regex fix with a test that genuinely fails on
the old code is the only way to keep this from recurring. The reviewer's other
notes (L-1 arithmetic, L-2 dead guard) were addressed trivially: the dead
`if end <= start` guard became an `assert end > start` so the invariant is
explicit instead of vestigial.

## Decisions

- Boundary priority is paragraph > Latin-sentence > CJK-sentence > word > hard cut.
- `split_for_digest` returns `DigestSections`, not `list[str]`; both in-tree
  callers updated; re-exported from `app.services.knowledge`.
- `digest_meta` gains additive keys `truncated`, `dropped_chars`, `source_chars`
  on the JSONB column; no migration, no schema-strengthening, no API change.
- `DIGEST_SECTION_OVERLAP = 400` extracted to `config.py`; value unchanged
  (overlap *tuning* is out of scope — would change chunk content and require
  reasoning about reindex cost, separate decision).
- Canonical Markdown path is untouched; `digest_sections` stays `None` there
  and the meta ternaries fall back to `False`/`0`/`len(raw)`.
- Embedding-input concatenation strategy (audit item #5) deliberately *not*
  changed — that changes vectors and needs a corpus reindex, larger-risk PR.

## Next

The change is verified: `ruff check .` clean, 71/71 knowledge tests pass,
7/7 `split_for_digest` tests pass (CJK test would fail on pre-fix code).
Unblocks `260718-1946-kb-rag-quality-and-grounding` phase 4 (corpus-wide
chunk dedup) — that plan now operates on correctly-bounded chunks. No commit
or deploy was performed; user has not requested it.

Status: DONE
Summary: `split_for_digest` now cuts on boundaries, never duplicates or silently
drops the tail, and reports truncation via `DigestSections` + `digest_meta`;
CJK sentence snap is real, not coincidental.
Concerns/Blockers: None. Embedding-input concatenation remains a known
follow-up (#5 in the audit) requiring a separate reindex-aware change.
