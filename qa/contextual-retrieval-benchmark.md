# Contextual Retrieval benchmark — chunk context prefix lúc index

Feature: `rag_contextual_enabled` (default **on**) — `backend/app/services/knowledge/contextual.py`.
Tại INDEXING, mỗi digest chunk được prepend 1 câu ngữ cảnh tài liệu (tên tài liệu + tóm tắt
digest + anchor/chủ đề của chunk) **trước khi embed**. Prefix xây metadata-first (không gọi
LLM thêm — digest đã sinh sẵn tóm tắt), deterministic, lưu riêng dưới
`knowledge_chunks.metadata.contextual_prefix` (content gốc không đổi).

Tham chiếu: Anthropic, *Contextual Retrieval* (2024) — −49% failed retrievals, −67% kèm rerank.

## Phương pháp

- Bộ đo: offline Vietnamese RAG gold set (`backend/tests/fixtures/rag_gold/`, 54 cases /
  28 chunks, trong đó 8 bait cases phải abstain) qua `scripts/benchmark_rag.py --gold`
  — cùng đường chạy post-retrieval như production (vector cosine + dedup + conditional rerank),
  không cần DB/network.
- Embedder giữ **hằng số** across before/after: `OpenRouterEmbedder`
  (`text-embedding-3-large`, 3072-dim) seed lại **cả hai** biến thể cùng lúc:
  - BEFORE: `scripts/seed_rag_gold_embeddings.py` (embed input = nội dung chunk, không prefix)
  - AFTER: `scripts/seed_rag_gold_contextual_embeddings.py` (embed input = production prefix
    + nội dung; **query embeddings copy nguyên xi** từ BEFORE — chỉ đổi phía index, không đổi query)
- Lưu ý phiên bản: `embeddings.json` check-in trước đó là artifact 54-dim cũ (không còn khớp
  embedder hiện tại). Cả hai file embedding được seed lại ở 3072-dim trong branch này;
  file cũ backup tại thời điểm đo (pass-rate 100%/mrr 0.8519 nhưng so le với model hiện tại).

## Kết quả (verbatim)

### BEFORE — không prefix (`embeddings.json` seed lại, cùng embedder)

```
Gold set: 54 cases, 50 passed (92.6%), 8/8 bait cases abstained.
  precision@3=0.2654  precision@5=0.1667  recall@10=0.9907  mrr=0.7525
```

### AFTER — contextual prefix (`embeddings_contextual.json`)

```
Contextual gold set: 54 cases, 54 passed (100.0%), 8/8 bait cases abstained.
  precision@3=0.3025  precision@5=0.1815  recall@10=1.0000  mrr=0.8025
```

## So sánh

| Metric | BEFORE | AFTER | Δ |
|---|---|---|---|
| Pass rate (54 cases) | 92.6% (50/54) | **100.0% (54/54)** | +7.4đ, **4 case thoát failed retrieval (4 → 0, −100%)** |
| precision@3 | 0.2654 | 0.3025 | +0.0371 (+14.0%) |
| precision@5 | 0.1667 | 0.1815 | +0.0148 (+8.9%) |
| recall@10 | 0.9907 | **1.0000** | mọi expected chunk vào top-10 |
| mrr | 0.7525 | 0.8025 | +0.0500 (+6.6%) |
| Bait abstain | 8/8 | 8/8 | không đổi — prefix không gây bait dính bẫy |

4 case thoát failed retrieval (trước đây expected chunk không đạt/leo nổi top):

- `lgd_dorm_fee` — "Phí ký túc xá LG Display bao nhiêu một tháng?" (mrr 0.17 → 1.00)
- `lgd_role_oled` — "Công nhân LG Display làm về sản phẩm gì?" (mrr 0.20 → 1.00)
- `lgd_vacancy_role` — "Công việc công nhân LG Display là gì?" (mrr 0.17 → 1.00)
- `lgd_salary_trial` — "Lương thử việc ở LG Display?" (mrr 0.10 → 0.33)

Điểm mrr tăng mạnh thêm (không đổi pass): `lgd_salary_total` 0.50 → 1.00,
`lgd_allowance_transport` 0.50 → 1.00, `lgd_allowance_lunch` 0.50 → 1.00.
**Không có case nào thụt lùi.**

## Chạy lại

```bash
cd backend
set -a; source .env; set +a   # OPENROUTER_API_KEY cho lần seed (benchmark thì offline)
.venv/bin/python scripts/seed_rag_gold_embeddings.py                # BEFORE (check-in)
.venv/bin/python scripts/seed_rag_gold_contextual_embeddings.py     # AFTER (check-in)
.venv/bin/python scripts/benchmark_rag.py --gold --min-pass-rate 0  # BEFORE
.venv/bin/python scripts/benchmark_rag.py --gold --min-pass-rate 0 \
    --embeddings tests/fixtures/rag_gold/embeddings_contextual.json # AFTER
```

Dữ liệu chunk/query (`cases.json`, `chunks.json`) đổi → seed lại cả hai file trước khi so.

## Backfill dữ liệu cũ

```bash
python -m scripts.backfill_contextual_prefix --dry-run   # xem kế hoạch
python -m scripts.backfill_contextual_prefix             # re-embed theo document, idempotent
```

Chunk đã có prefix (metadata `contextual_prefix`), canonical chunk (đã có `contextual_text`
theo spec), và category-revision chunk (đường index riêng, không đổi) được bỏ qua.
