# 2026-10-02 — Evidence grounding: compare words, not formatting

## Symptom (operator report)

Two complaints on the same project (`4P Electronics`, prod id `e1fcceee-…`):

1. The project list read **"Thông tin tư vấn 4/12"** while the panel underneath
   read **"12/12 danh mục có dữ liệu"**.
2. Uploading `4p-electronics.md` to the knowledge base showed **"Lỗi nạp"**.

## What was actually wrong

Both are one defect: the LLM-output evidence gates compared **raw strings**, so a
genuine quote that did not match the source byte-for-byte was judged fabricated.

- Category lane (`category_plan_grounding.validate_category_envelope` +
  `extract_category_plan`): quotes were matched as whitespace-folded substrings,
  and every field value had to be a substring of the record's own cited quotes.
  The provider (production digest model) reliably cites a brief's **words**
  without the brief's markdown (`- **Kỳ hạn trả lương:** Trả lương theo tháng.` →
  `Kỳ hạn trả lương: Trả lương theo tháng.`), it composes one field from several
  lines, and it cites a subset of those lines. Every one of those was a hard
  failure, and **one bad record failed the entire file** — hence "Lỗi nạp".
  Production log: `extraction.py:255 raise ... "Category record has no matching
  source quote"` for document `19d372ba-…`.
- Feature lane (`coercion._coerce_feature`): the whole `evidence_text` had to be
  one folded substring of the source. The prompt explicitly asks for the
  *relevant lines* when an answer spans several lines, so the model's honest
  evidence — several lines, or those lines joined into one — never matched. A
  reproduction of the real `KnowledgePipeline.extract_product_features` against
  the real file with the production model returned **12 concrete answers and
  published 0/12**. Commit `6926f87e` had just made that degradation silent per
  candidate, so the counter froze at whatever the last successful run left
  (4/12) and would have read 0/12 after the next successful upload.

## The rule now

Grounding compares **content, not formatting**:

- Text is folded to word tokens (NFC + casefold, letters and digits only) for
  containment checks. Numbers, times, enums and service denials keep the
  punctuation-sensitive path they need.
- Feature evidence is split into line **and sentence** segments; each segment
  must appear as one uninterrupted word run in the source. Quoted words the
  source does not contain still fail.
- Category-plan quotes must be verbatim (word-for-word) source text.
- Category-plan **field values are grounded against the whole source section**,
  not only the record's cited quotes: a subset citation is not a fabrication.
  The quotes remain verified-verbatim as the audit trail.
- Anything the source does not support is **cleared from the record** (scalar
  list items are removed), then the record is re-validated: if it is left with
  no facts, or no longer satisfies its schema, the record is dropped — and the
  rest of the file still trains.
- `extract_category_plan` now drops ungrounded records instead of aborting the
  document, and raises the new mapped message
  `"Bản ghi trích xuất chưa khớp với nguồn tệp. Vui lòng kiểm tra tệp rồi thử lại."`
  only when *nothing* survived — a failed mapping must never look like an empty
  source.

## Rejected alternatives

- **Prompt-only fix** ("tell the model to quote with markdown"): non-deterministic
  and re-breaks on the next model change.
- **Bag-of-words grounding** (value words present anywhere, any order): accepts
  reordered/negation-flipped evidence. Kept contiguity instead.
- **Keeping the all-or-nothing gate** and only relaxing the string compare: still
  fails the real file, because two records join lines the source keeps apart.
- **Deleting the gate**: it is the anti-hallucination guard; unsupported salary,
  insurance, phone and housing claims must never publish.

## Verified

- Category lane: real file + saved provider output → all 12 categories written;
  a fresh production-model call → 11/12 (the model returned an empty
  `transportation` list that run). Previously: whole upload failed.
- Feature lane: real `extract_product_features` with the production digest model
  → `ready=11/12` on two independent calls (only `joining_bonus`, which the model
  reports as missing, stays empty). Previously 0/12 published.
- `pytest tests/ -k "knowledge or training or feature or categor or coerc or
  ingest or grounding"` → 801 passed, 12 failed; the same 12 fail with the change
  stashed (stale legacy-KB-lane tests from `2674fc79`). Ruff clean on the changed
  files, pyright 0 errors, architecture-boundary tests 21 passed.

## Next session notes

- Prod keeps showing 4/12 until this is deployed and the project ingests again:
  `19d372ba-…` is FAILED but is reused and requeued on the next upload of the
  same file, so a plain re-upload is enough; the manual feature re-extraction
  also refreshes it.
- A same-file re-upload of an already COMPLETED training source is a no-op retry
  (`training_source_reusable`), so feature values cannot be refreshed that way.
- Residual risk: field values grounded against the whole section are slightly
  easier to satisfy than quote-only grounding. Contiguity still blocks fabricated
  text, and the number/enum/denial checks are unchanged.
