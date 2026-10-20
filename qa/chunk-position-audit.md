# Chunk-position audit — Lost-in-the-Middle (RAG pack W1 mục 03)

Feature: `rag_context_order` (default **`position-aware`**, fallback `similarity`) —
`backend/app/graph/tools/knowledge.py` (`order_context_chunks`, `resolve_context_order`)
+ `backend/app/core/config.py` (`Settings.rag_context_order`) +
`backend/scripts/eval_answers.py` (`--context-order`).

Tham chiếu: Liu et al., *Lost in the Middle: How Language Models Use Long Contexts* (2023) —
LLM chú ý mạnh nhất ở **đầu** (primacy) và **cuối** (recency) của context dài; thông tin nằm
ở giữa bị suy giảm khả năng trích xuất ngay cả khi retrieval đã lấy đúng chunk.

---

## 1. Kiểm toán nơi lắp context & rủi ro stuffing ở `answer_cache`

### 1.1 Đường lắp context cho LLM (`search_knowledge` + routed prefetch + tool loop)

1. `backend/app/services/retrieval/document_repository.py` (`DocumentRepository.match_documents`):
   truy vấn `top_k=25` chunk với `SIMILARITY_FLOOR = 0.30`, trả về theo thứ tự cosine giảm dần.
2. `backend/app/graph/tools/knowledge.py` (`_search_knowledge_compute`):
   - chạy pre-pass `repo.match_faq(emb, top_k=3)` (`FaqRepository.FAQ_SIMILARITY_FLOOR = 0.55`,
     `category = 'faq'`) và prepend tối đa 3 FAQ chunk lên đầu danh sách `ordered`, sau đó nối
     các dòng `match_documents` (đã dedup theo `id`);
   - cắt theo ngân sách hiển thị `_render_capped_evidence(ordered)` (`_MAX_EVIDENCE_ROWS = 20`,
     `_MAX_EVIDENCE_CHARS = 20000`, `_MAX_EVIDENCE_ROW_CHARS = 4000`);
   - nối bằng `"\n".join(lines)` và bơm vào prompt của agent tại `backend/app/graph/clients.py`
     (routed prefetch dòng 465, 490, 588–694 hoặc `ToolMessage` trong tool loop dòng 884, 988).
3. `backend/scripts/eval_answers.py` (`_generate_answer_with`):
   ghép các chunk thành `[Đoạn 1] ... [Đoạn N]` trong `HumanMessage` ngay trước dòng
   `Câu hỏi: {question}`.

### 1.2 Kiểm tra rủi ro stuffing tại `answer_cache` và các tầng cache RAG

| Tầng cache | File | Giá trị lưu | Có nhồi thêm chunk vào prompt LLM? | Rủi ro thực tế với Lost-in-the-Middle |
|---|---|---|---|---|
| **Answer cache** (exact + semantic) | `backend/app/graph/answer_cache.py`, `backend/app/graph/lanes.py:995-1025, 1131-1138` | Chuỗi **câu trả lời cuối cùng của bot** (`reply: str`, 1 câu trả lời/key, TTL 6h = `21600s`) | **Không.** Khi cache hit (`lanes.py:1024`), worker trả thẳng `cached_answer.reply` về Zalo và **bỏ qua hoàn toàn LLM** (không lắp context). | **Rủi ro khuếch đại (amplification risk):** nếu ở lượt cache-miss đầu tiên, chunk đúng bị chôn ở giữa context dài (13–20 chunks) khiến LLM bỏ sót chi tiết mà câu trả lời vẫn qua được `is_shareable_reply()`, `answer_cache_put` sẽ ghim câu trả lời thiếu đó suốt **6 giờ** cho mọi câu hỏi trùng. |
| **RAG exact cache** | `backend/app/graph/tools/knowledge.py:202-235, 413-415` | Chuỗi evidence đã ghép (`"\n".join(lines)`, tối đa 20 chunks / 20.000 ký tự, TTL 300s) | Lưu nguyên chuỗi multi-chunk của 1 lần gọi `search_knowledge` (không cộng dồn qua nhiều lượt). | **Rủi ro stale ordering:** cache lưu chuỗi đã render theo thứ tự chunk. Đã tách namespace `cache_format` theo `rag_context_order` để đổi cờ env không bao giờ đọc nhầm thứ tự cũ từ Redis. |
| **RAG semantic cache** | `backend/app/graph/semantic_cache.py:216-306` | `best_entry.result` (1 entry có cosine cao nhất `>= 0.95`, TTL 1800s) | Chỉ trả 1 `best_entry` (không ghép nhiều entry). | Cũng lưu chuỗi evidence đã render → đã gắn `cache_format` vào `sem_scope`. |

---

## 2. Đo vị trí (rank) của gold chunk trên bộ Golden Set & phân tích rủi ro

### 2.1 Độ dài context thực tế (`top_k=25`, `SIMILARITY_FLOOR=0.30`)

Do `SIMILARITY_FLOOR = 0.30` giữ lại hầu hết các chunk cùng dự án:
- Trên `rag_gold` (46 non-bait cases): phân bố số chunk `N` trong context là
  `{3: 3, 4: 7, 6: 12, 12: 5, 13: 19}` → **36/46 cases (78.3%) có context dài `> 5` chunks**
  (Samsung `N = 6`, LG Display `N = 12–13`).
- Trên `tests/golden/answers.yaml` (33 non-abstain cases): phân bố `N` là
  `{3: 2, 4: 4, 6: 6, 12: 3, 13: 18}` → **27/33 cases (81.8%) có context dài `> 5` chunks**.

### 2.2 Histogram vị trí của gold chunk trước khi reorder (`similarity` order)

1. **Trên `tests/golden/answers.yaml` (33 non-abstain cases, 35 gold chunk hits — `embeddings.json`):**
   - Histogram rank/position (1-based):
     - Vị trí `1` (đầu context): **27 chunks**
     - Vị trí `2` (ngay sau đầu, trong context 13 chunks): **5 chunks** (`ans-lgd-salary-official`, `ans-lgd-salary-total`, `ans-lgd-allowance-transport`, `ans-lgd-allowance-lunch`, `ans-lgd-apply-phone`)
     - Vị trí `4` (giữa, `N=13`): **1 chunk** (`ans-lgd-salary-official` — chunk gold thứ 2)
     - Vị trí `6` (chính giữa, `N=13`): **1 chunk** (`ans-lgd-dorm-fee`)
     - Vị trí `10` (giữa-cuối, `N=13`): **1 chunk** (`ans-lgd-salary-trial`)
     - Vị trí `N` (cuối context — recency edge): **0 chunks (0.0%)** — vị trí sát câu hỏi nhất luôn bị chiếm bởi chunk nhiễu có cosine thấp nhất (~0.33–0.45).
   - Tính theo case trên context dài (`N > 5`, 27 cases): **6/27 cases (22.22%)** không có bất kỳ gold chunk nào ở rìa đầu/cuối (`1 < pos < N`), và nếu tính mọi gold chunk thì **7/33 cases (21.2%)** có gold chunk nằm ở phần ruột context.

2. **Trên toàn bộ `rag_gold` (46 non-bait cases, 49 gold chunk hits):**
   - `embeddings.json` (vector order): `{1: 38, 2: 5, 4: 1, 5: 1, 6: 2, 10: 1, 12: 1}` — **10/46 cases (21.7%)** có gold chunk rơi vào giữa context dài (`N = 12–13`), điển hình:
     `lgd_salary_trial` (pos `10/13`), `lgd_dorm_fee` (pos `6/13`), `lgd_vacancy_role` (pos `6/13`),
     `lgd_role_oled` (pos `5/12`), `lgd_pay_synonym` (pos `[1, 12]/13`), `lgd_salary_official` (pos `[2, 4]/13`).
   - Khi đi qua `search_knowledge` (FAQ-first pre-pass ghép tối đa 3 chunk `category='faq'` có `sim >= 0.55` lên trước):
     histogram bị đẩy sâu hơn vào giữa:
     - `embeddings.json`: `{1: 34, 2: 4, 4: 4, 5: 1, 6: 2, 10: 1, 12: 1}` (**14/46 = 30.4%** cases rơi vào giữa).
     - `embeddings_contextual.json`: `{1: 34, 2: 4, 3: 3, 4: 8}` (**14/46 = 30.4%** cases rơi vào giữa, vì các gold chunk `category='general'` như `lgd_contact_chunk_01`, `lgd_role_chunk_01`, `lgd_dorm_chunk_01` dù đạt rank 1 ở `match_documents` vẫn bị 3 FAQ chunk đẩy xuống vị trí `4/13`).

**Kết luận phân tích:** Rủi ro Lost-in-the-Middle là **có thật**: ~78–82% truy vấn tạo context dài (`6–13` chunks), **18.2%–30.4%** truy vấn có chunk đáp án rơi vào phần giữa context, và **0%** tận dụng được rìa cuối (recency edge) ngay sát câu hỏi.

---

## 3. Thiết kế & Implementation (`rag_context_order=position-aware`)

- Thêm setting `rag_context_order: str = "position-aware"` trong `backend/app/core/config.py`
  (validate nhận `"position-aware"` và `"similarity"` / `"rank"`).
- Hàm `order_context_chunks(chunks, *, order=...)` trong `backend/app/graph/tools/knowledge.py`:
  - Giữ nguyên bước cắt ngân sách `_render_capped_evidence(ordered)` theo đúng thứ tự rank để không làm rơi top hits.
  - Khi `order == "position-aware"` và `len(chunks) > 2`, sắp xếp đan xen từ hai biên vào tâm:
    `left = chunks[0::2]` (ranks `1, 3, 5, ...` từ đầu xuống), `right = list(reversed(chunks[1::2]))`
    (ranks `..., 6, 4, 2` tiến dần về cuối):
    - **Rank 1** → vị trí `1` (đầu context — primacy edge)
    - **Rank 2** → vị trí `N` (cuối context — recency edge, ngay sát `Câu hỏi:`)
    - **Rank 3** → vị trí `2` (sát đầu)
    - **Rank 4** → vị trí `N - 1` (sát cuối — cứu trực tiếp các chunk `general` đứng sau 3 FAQ chunk!)
    - Các chunk điểm thấp nhất (`rank N`, `rank N-1`) bị đẩy vào chính giữa (`pos = N // 2`).

### Hiệu quả dịch chuyển vị trí gold chunk (`answers.yaml`, 33 non-abstain cases)

| Cấu hình embedding | Chế độ `rag_context_order` | Histogram vị trí gold chunk (1-based) | Tỷ lệ ở biên đầu/cuối (`edge_rate`, pos `1` hoặc `N`) | Tỷ lệ kẹt ở giữa (`middle_rate`) | Tỷ lệ kẹt ở giữa khi `N > 5` (`long_context_middle_rate`) |
|---|---|---|---|---|---|
| `embeddings.json` | `similarity` (BEFORE) | `{1: 27, 2: 5, 4: 1, 6: 1, 10: 1}` | 81.82% (27/33) | 18.18% (6/33) | 22.22% (6/27) |
| `embeddings.json` | `position-aware` (AFTER) | `{1: 27, 9: 1, 11: 1, 12: 1, 13: 5}` | **93.94% (31/33)** (**+12.12 pts**) | **6.06% (2/33)** (**−12.12 pts**) | **7.41% (2/27)** (**−14.81 pts**) |
| `embeddings_contextual.json` | `similarity` (BEFORE) | `{1: 29, 2: 4, 3: 2}` | 87.88% (29/33) | 12.12% (4/33) | 14.81% (4/27) |
| `embeddings_contextual.json` | `position-aware` (AFTER) | `{1: 29, 2: 2, 13: 4}` | **96.97% (32/33)** (**+9.09 pts**, 100% ở `{1, 2, 13}`) | **3.03% (1/33)** (**−9.09 pts**) | **3.70% (1/27)** (**−11.11 pts**) |

---

## 4. Kết quả `scripts/eval_answers.py` trước/sau (Verbatim)

Lệnh chạy trên cùng 39-case golden set (`backend/tests/golden/answers.yaml`), live generation + DeepEval LLM judge (`deepseek/deepseek-v3.2` qua OpenRouter):

```bash
cd backend
unset PYTHONPATH
set -a; source .env; set +a
MINIMAX_ENABLE=false OPENROUTER_ENABLE=true .venv/bin/python -m scripts.eval_answers \
    --rerank off --context-order both --judge on --concurrency 8 --output /tmp/chunkpos_eval.json
```

### Output verbatim từ `scripts/eval_answers.py`

```text
== eval run: rag_context_order=similarity (rerank=False) ==
  [5/39] cases scored (rerank=False, order=similarity)
  [10/39] cases scored (rerank=False, order=similarity)
  [15/39] cases scored (rerank=False, order=similarity)
  [20/39] cases scored (rerank=False, order=similarity)
  [25/39] cases scored (rerank=False, order=similarity)
  [30/39] cases scored (rerank=False, order=similarity)
  [35/39] cases scored (rerank=False, order=similarity)
  [39/39] cases scored (rerank=False, order=similarity)
rerank=False answers=live judge=True cases=39 judged=39 errored=0
  mean_precision_at_3     0.2735
  mean_precision_at_5     0.1692
  mean_recall_at_10       1.0000
  mean_mrr                0.7504
  fact_hit_rate           0.9545
  faithfulness            0.9872
  answer_relevancy        0.7984
  contextual_precision    0.8338
  contextual_recall       0.8462
== eval run: rag_context_order=position-aware (rerank=False) ==
  [5/39] cases scored (rerank=False, order=position-aware)
  [10/39] cases scored (rerank=False, order=position-aware)
  [15/39] cases scored (rerank=False, order=position-aware)
  [20/39] cases scored (rerank=False, order=position-aware)
  [25/39] cases scored (rerank=False, order=position-aware)
  [30/39] cases scored (rerank=False, order=position-aware)
  [35/39] cases scored (rerank=False, order=position-aware)
  [39/39] cases scored (rerank=False, order=position-aware)
rerank=False answers=live judge=True cases=39 judged=39 errored=0
  mean_precision_at_3     0.2735
  mean_precision_at_5     0.1692
  mean_recall_at_10       1.0000
  mean_mrr                0.7504
  fact_hit_rate           1.0000
  faithfulness            0.9701
  answer_relevancy        0.8256
  contextual_precision    0.8338
  contextual_recall       0.8205

metric                      similarity  position-aware  lift (pts)
------------------------------------------------------------------
mean_precision_at_3             0.2735          0.2735      +0.000
mean_precision_at_5             0.1692          0.1692      +0.000
mean_recall_at_10               1.0000          1.0000      +0.000
mean_mrr                        0.7504          0.7504      +0.000
fact_hit_rate                   0.9545          1.0000      +4.545
faithfulness                    0.9872          0.9701      -1.709
answer_relevancy                0.7984          0.8256      +2.721
contextual_precision            0.8338          0.8338      +0.000
contextual_recall               0.8462          0.8205      -2.564
------------------------------------------------------------------
edge_rate                       0.8182          0.9394     +12.120
middle_rate                     0.1818          0.0606     -12.120
long_context_middle_rate        0.2222          0.0741     -14.810
```

### Bảng tổng hợp các case dịch chuyển vị trí tiêu biểu (`N = 13`)

| Case ID | Retrieval rank(s) | Vị trí trong context (`similarity` → `position-aware`) | `answer_relevancy` (BEFORE → AFTER) | `faithfulness` (BEFORE → AFTER) |
|---|---|---|---|---|
| `ans-lgd-salary-official` | `[2, 4]` | `[2, 4] / 13` → **`[12, 13] / 13`** (sát cuối & cuối) | `0.5714` → **`1.0000`** (+42.9 pts) | `1.0000` → `1.0000` |
| `ans-lgd-salary-total` | `[2]` | `[2] / 13` → **`[13] / 13`** (cuối) | `0.7500` → **`0.8333`** (+8.3 pts) | `1.0000` → `1.0000` |
| `ans-lgd-salary-trial` | `[10]` | `[10] / 13` → **`[9] / 13`** | `0.7500` → **`1.0000`** (+25.0 pts) | `1.0000` → `1.0000` |
| `ans-lgd-dorm-fee` | `[6]` | `[6] / 13` (tâm) → **`[11] / 13`** (gần cuối) | `0.4000` → **`0.5000`** (+10.0 pts) | `1.0000` → `1.0000` |
| `ans-lgd-apply-phone` | `[1, 2]` | `[1, 2] / 13` → **`[1, 13] / 13`** (đầu + cuối) | `1.0000` → `0.7500` | `1.0000` → `1.0000` |
| `ans-lgd-allowance-lunch` | `[2]` | `[2] / 13` → **`[13] / 13`** (cuối) | `1.0000` → `0.8333` | `1.0000` → `1.0000` |
| `ans-lgd-allowance-transport` | `[2]` | `[2] / 13` → **`[13] / 13`** (cuối) | `0.6667` → `0.5000` | `1.0000` → `1.0000` |

**Nhận xét:**
- `fact_hit_rate` đạt **1.0000 (100% trên toàn bộ 33 câu non-abstain, +4.545 pts)** và `answer_relevancy` tăng **+2.721 pts** (`0.7984 → 0.8256`), đặc biệt ở các câu hỏi nhiều thành phần như `ans-lgd-salary-official` (`+42.9 pts`), `ans-lgd-salary-trial` (`+25.0 pts`), `ans-lgd-dorm-fee` (`+10.0 pts`), `ans-lgd-salary-total` (`+8.3 pts`) khi chunk quan trọng được đưa về sát câu hỏi ở cuối context.
- `faithfulness` giữ ở mức rất cao (`0.9701`, vượt xa ngưỡng gate `0.75`).
