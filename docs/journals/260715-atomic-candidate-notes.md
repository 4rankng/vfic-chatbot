---
date: 2026-07-15
session: atomic-candidate-notes
---

# Journal: 2026-07-15 — Atomic candidate notes

## Context

Candidate notes accumulated repeated summaries because each extraction turn
could restate previously stored information in different wording. The fix needed
to preserve the existing nullable text field and API while making new notes
short, independently useful, and duplicate-safe.

## What Happened

- The extraction prompt now requires one atomic fact per newline, forbids
  conversation summaries and paraphrases of saved facts, and returns `null` when
  the current user message contributes no new note.
- Existing notes are loaded before extraction and supplied to the LLM as
  comparison-only context. They are not candidate-message evidence.
- Backend normalization removes presentation bullets, collapses whitespace, and
  deduplicates exact normalized identities using case and trailing-punctuation
  normalization. It deliberately does not perform fuzzy semantic matching.
- The PostgreSQL conflict upsert splits incoming and stored notes into lines and
  appends only missing normalized identities within the same statement, keeping
  concurrent persistence at the database boundary.
- Review caught a decimal-leading regression in the bullet-prefix pattern:
  facts such as `1.5 năm kinh nghiệm` and `2.000.000 đồng phụ cấp` could lose
  their numeric prefixes. Requiring whitespace after numbered bullets fixed the
  backend and frontend paths.
- Verification passed: 94 focused backend tests, 1,109 full backend tests, and
  four frontend candidate-note formatter tests. Ruff, frontend type-check, and
  focused frontend lint/format checks also passed.

## Reflection

Prompt guidance reduces duplicate generation, but deterministic normalization
and the PostgreSQL upsert remain necessary because model compliance is not a
persistence guarantee. Exact matching is intentionally conservative: retaining
two semantic paraphrases is safer than deleting distinct candidate facts via a
fuzzy heuristic. The decimal case also showed why shared-looking text rules need
regression coverage on both write and display boundaries.

## Decisions Made

| Decision                                              | Rationale                                                         | Impact                                                              |
| ----------------------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------- |
| Store atomic facts as newline-separated text          | Preserves the current schema and API                              | No migration or backfill                                            |
| Give the LLM saved notes as comparison-only context   | Discourages summaries and repeated facts at extraction time       | New output should contain only current-message facts                |
| Deduplicate deterministic exact normalized identities | Behavior is explainable and avoids false-positive semantic merges | No fuzzy cleanup of historical paraphrases                          |
| Filter again in the PostgreSQL upsert                 | The persistence boundary must not depend on prompt compliance     | Duplicate normalized lines are not appended by the upsert statement |

## Next Steps

- Observe new production notes after approved deployment for prompt-compliance
  drift and unexpected atomicity issues.
- Treat historical semantic cleanup as a separate, explicitly reviewed task if
  it becomes necessary; this change performs no migration or fuzzy rewrite.
