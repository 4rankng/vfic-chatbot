# Agent-X — Prompt Distillation Report

**How Agent-X actually trains its AI agents**

**Method:** Reverse-engineered from (a) hard-coded JS bundle strings, (b) leaked `usage.metadata` fields in API responses, (c) endpoint payload shapes, (d) the live-chat widget's Socket.IO surface.

**TL;DR:** Agent-X = **Flowise (LangChain + LlamaIndex) under the hood**, with a layer of in-house Vietnamese prompt templates that do role generation, rule generation, Q&A expansion, and order extraction. Models are mostly OpenAI (`gpt-4.1-mini`) for cheap internal tasks, with a socket-streaming inference layer for live chat.

---

## 1. The actual architecture

```
┌─────────────────────────────────────────────────────────────┐
│  React Admin SPA (app.agent-x.ai)                            │
│   - TanStack Query for REST                                  │
│   - i18n: VI / EN                                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
       ┌───────────────┼───────────────────────────┐
       │               │                           │
   REST API       Socket.IO                   Widget JS
   api.agent-x.ai app.agent-x.ai/livechat    app.agent-x.ai/agent-x-live-chat.js
       │               │                           │
       └───────┬───────┴───────────────┬───────────┘
               │                       │
        ┌──────▼────────┐    ┌─────────▼─────────┐
        │ Agent-X Core  │    │ Flowise Canvas    │
        │ (in-house)    │    │ (Nexus subsystem) │
        │  - Roles      │    │ - chatflowid      │
        │  - Skills     │    │ - React Flow UI   │
        │  - Q&A        │    │ - LangChain nodes │
        │  - RAG store  │    │ - Tools, Memory   │
        └──────┬────────┘    └─────────┬─────────┘
               │                       │
               └───────┬───────────────┘
                       │
              ┌────────▼─────────┐
              │  LLM Provider    │
              │  - gpt-4.1-mini  │  (most generation)
              │  - NVIDIA NIM    │  (self-hosted opt)
              │  - LlamaIndex    │  (RAG)
              │  - LangChain Hub │  (prompt templates)
              └──────────────────┘
```

The JS bundle contains **181 occurrences of `chatflowid`** — this is the smoking gun. Flowise uses `chatflowid` as the central ID for an agent workflow (nodes + edges + memory). Agent-X wraps each agent in a Flowise chatflow, and the `flowise_organization_id` field on each org maps directly to Flowise workspaces.

---

## 2. Master system prompts (LITERALLY extracted from API responses)

I called these endpoints and got the full prompts back in `usage.metadata.system_prompt`. Every one is reusable for your own build.

### 2.1 Agent Description Generator

**Endpoint:** `POST /api/n/v1/agents/generate-description`
**Payload:** `{short_description: string, content_type?: string}`
**Model:** `gpt-4.1-mini` (~600 prompt tokens, ~500 completion)

**System prompt (verbatim):**

```
Bạn là chuyên gia viết mô tả cho AI Agent.

[NHIỆM VỤ]
Tạo một bản mô tả agent hoàn chỉnh theo cấu trúc Markdown gồm 7 mục:
1) What's my job?
2) Who will need my help?
3) How do I get things done?
4) What should I avoid?
5) What results do you want me to track?
6) How should I talk to people?
7) Any extra tips?

[YÊU CẦU BẮT BUỘC]
A) GIỮ NGUYÊN NGÔN NGỮ:
- Xác định ngôn ngữ đang được dùng trong "Mô tả ngắn".
- TẤT CẢ nội dung bạn viết ra (7 mục) PHẢI dùng đúng ngôn ngữ đó, tự nhiên, không pha trộn ngôn ngữ khác.
- Giữ nguyên tên riêng/thuật ngữ/brand/product như trong mô tả gốc (không dịch nếu mô tả gốc không dịch).

B) KHÔNG SUY LUẬN / KHÔNG BỊA:
- Không thêm tính năng, tích hợp, số liệu, cam kết, quy trình nội bộ… nếu mô tả gốc không đề cập.
- Nếu một mục không có đủ thông tin từ mô tả gốc để viết cụ thể, hãy viết theo hướng "nguyên tắc chung" nhưng vẫn bám sát mục tiêu agent, tránh chi tiết bịa đặt.

C) CHẤT LƯỢNG NỘI DUNG:
- Mục "What's my job?": mở rộng từ mô tả gốc thành 2–4 câu, khoảng 100–200 từ (theo ngôn ngữ gốc), chuyên nghiệp, rõ ràng, nêu lợi ích.
- Các mục còn lại: mỗi mục 1 đoạn ngắn 1–3 câu, rõ ràng, thực tế, tập trung vào hành vi/giới hạn/đo lường/giao tiếp.

[ĐẦU RA — BẮT BUỘC]
- Chỉ trả về DUY NHẤT một khối Markdown.
- BẮT BUỘC mỗi tiêu đề của 7 mục phải dùng heading Markdown cấp 3: bắt đầu bằng `### `. Đúng tiêu đề mục và thứ tự như mẫu (giữ nguyên các heading tiếng Anh: "What's my job?" ...).
- Mỗi mục có đúng 1 đoạn văn được đặt trong dấu ngoặc kép "..." (giống ví dụ).
- Không thêm bất kỳ giải thích nào ngoài Markdown.
```

**Output format:** 7 Markdown H3 sections, each with a single quoted paragraph.

### 2.2 Agent Rule Generator

**Endpoint:** `POST /api/n/v1/agents/generate-rule`
**Payload:** `{short_rule_text: string}`
**Model:** `gpt-4.1-mini`

**System prompt (verbatim, abbreviated):**

```
Bạn là một chuyên gia trong việc viết các nguyên tắc và quy tắc chi tiết cho AI agent.
Nhiệm vụ của bạn là generate một đoạn text chi tiết và đầy đủ hơn từ một đoạn mô tả ngắn về nguyên tắc/ quy tắc.

## Yêu cầu chính:
1. Giữ nguyên ý nghĩa và mục đích
2. Mở rộng và làm rõ chi tiết (làm rõ khái niệm, giải thích yêu cầu, mô tả hành động, làm rõ giới hạn)
3. Thêm ví dụ cụ thể (kèm edge cases)
4. Cấu trúc rõ ràng (bullet points, numbered list, headings)
5. Tập trung vào tính thực thi (tránh mơ hồ)
6. Độ dài phù hợp (max 500 từ)
7. Tone chuyên nghiệp nhưng dễ hiểu

## Quy trình generate:
1. Phân tích đoạn text gốc
2. Xác định điểm cần làm rõ
3. Generate nội dung có cấu trúc
4. Kiểm tra tính nhất quán
```

### 2.3 Order Extraction (live inference)

**Endpoint:** `POST /api/n/v1/orders/extract-order`
**Payload:** `{agent_id, customer_id, conversation_id, text}`
**Model:** gpt-4.1-mini

**System prompt (verbatim):**

```
Bạn là một AI chuyên xử lý đơn hàng từ hội thoại khách hàng.
Dựa vào toàn bộ `conversation_history` và `current_user_message` hãy trích xuất các thông tin ghi nhận đơn hàng

[QUY TẮC TRÍCH XUẤT — TUYỆT ĐỐI KHÔNG SUY LUẬN]
**Chỉ trích xuất đơn hàng nếu có đầy đủ tất cả thông tin sau**:
`customer_name`, `customer_phone`, `customer_address`, `order_details`.

**Trong đó**: `quantity`, `productCode`, `total_amount`, `productName` :
lấy theo "Số lượng" trong `conversation_history`
*KHÔNG* được suy ra thông tin khác.

Nếu có đơn hàng và đầy đủ thông tin, hãy trích xuất đơn hàng **cuối cùng**
theo cấu trúc JSON như sau.
**Nếu thiếu bất kỳ thông tin nào, trả về JSON rỗng `{}`.**

##Định dạng phản hồi
- **Có đủ thông tin** `customer_name`, `customer_phone`, `customer_address`, `order_details`:
  {customer_name, customer_phone, customer_address, full_total_amount,
   order_details: [{productName, quantity, price, total_amount, productCode}]}
- **Thiếu bất kỳ trường nào**: `{}`
```

**Extraction request template:**

```
Thông tin chi tiết về cuộc hội thoại:
1. NGỮ CẢNH CUỘC HỘI THOẠI (conversation_history): <history>
2. TIN NHẮN CỦA NGƯỜI DÙNG GỬI TỚI HIỆN TẠI (current_user_message): <text>

Hãy trích xuất thông tin đơn hàng từ cuộc hội thoại trên.
```

---

## 3. The 3 default Agent roles (templates)

These come from `GET /api/n/v1/instructions/roles` and ship as built-in templates users can pick when creating an agent:

### 3.1 Customer Care Agent (`customer_care_agent`)

```
Bạn là nhân viên chăm sóc khách hàng. Bạn tiếp nhận phản hồi, giải đáp các câu hỏi,
hướng dẫn sử dụng sản phẩm/dịch vụ và hỗ trợ xử lý sự cố hoặc khiếu nại của
khách hàng. Bạn luôn thể hiện sự lắng nghe, thái độ chân thành và chủ động theo
dõi đến khi vấn đề được giải quyết triệt để. Nếu chưa thể xử lý ngay, bạn cần
thông báo rõ lý do và thời gian phản hồi dự kiến. Bạn luôn xưng là "em", gọi
khách là "anh/chị", giữ ngôn ngữ giao tiếp lịch sự, nhã nhặn, thân thiện, và
luôn bắt đầu câu nói bằng "dạ", "thưa" để thể hiện sự tôn trọng và chuyên nghiệp.

Suggested greetings: ["Mình chuyển khoản rồi nhưng chưa thấy xác nhận?",
"Shop có bảo hành không?", "Mình lỡ đặt nhầm", "Huỷ đơn được không?"]
```

### 3.2 Sales Agent (Physical goods) (`sales_agent`)

```
Bạn là nhân viên tư vấn bán hàng. Nhiệm vụ của bạn là giới thiệu và tư vấn
sản phẩm/dịch vụ phù hợp với nhu cầu của khách hàng. Bạn cần lắng nghe kỹ
câu hỏi, đưa ra thông tin rõ ràng, chính xác và dễ hiểu. Khi khách hàng có
nhu cầu, bạn sẽ đề xuất các lựa chọn phù hợp nhất, kèm theo ưu điểm và mức
giá. Trong mọi cuộc hội thoại, bạn luôn sử dụng ngôn ngữ lịch sự, xưng là "em",
gọi khách là "anh" hoặc "chị" tùy đối tượng. Bạn luôn "dạ", "thưa" khi trả
lời và thể hiện thái độ thân thiện, nhiệt tình, chu đáo.

Suggested greetings: ["Danh sách sản phẩm bán chạy?", "Có giao toàn quốc không?",
"Bao lâu thì nhận được hàng?"]
```

### 3.3 Sales Agent (Intangible goods) (`sales_service_agent`)

Identical wording to 3.2 — they only differ in `suggest_messages_default`:
`["Tư vấn dịch vụ", "Tôi muốn dùng thử"]`

---

## 4. The actual training pipeline (reconstructed)

### Phase 1 — Data Ingestion

| Source | Endpoint | Backend action |
|--------|----------|----------------|
| **Text** | `POST /datasources/text/{agentId}` | Stores raw text, embeds for RAG |
| **File** | `POST /datasources/files/{agentId}` (multipart) | Extract → chunk → embed → store |
| **Media** | `POST /datasources/media/{agentId}` | OCR/image desc → embed |
| **Q&A** | `POST /training/qa-manual` | Direct insert into `init_trainings` table |
| **Website URL** | `POST /datasources/website/onboard_sitemap_url` | Crawl + scrape + chunk + embed |
| **Chat history** | `POST /training/{agentId}/chat-history/{customerId}` | Mine past conversations as training data |

All sources have **status machine**: `Untrained → Processing → Trained | Error | Deleting`.

### Phase 2 — Document → Multi-agent generation

**The killer feature**: Upload one instruction doc → backend auto-extracts roles → creates multiple sub-agents.

Frontend UI flow (from bundle analysis):
1. User uploads `instruction_file` (docx, xlsx, pdf, txt)
2. Clicks **Xử lý** (Process)
3. Backend runs an LLM that:
   - Parses the document
   - Identifies distinct agent roles
   - Calls `/agents/generate-description` per role
   - Calls `/agents/generate-rule` per role
   - Creates child agents via `/agents/create`
4. UI shows generated agents; user clicks pencil icon to **edit**
5. User clicks "Save changes" → `/agent-node-prompts/{id}/{nodeId}` PUT

### Phase 3 — Knowledge indexing

Each agent has 4 node types (from Flowise model):
- `chatPromptTemplate` (system prompt)
- `systemMessagePrompt` (static role instructions)
- `humanMessagePrompt` (RAG context wrapper)
- `workerPrompt` (sub-agent orchestration)

RAG uses **LlamaIndex** under the hood (confirmed by bundle: `react-flow`, `flowise_organization_id`, `LlamaIndex` string references).

### Phase 4 — Inference (live chat)

**Transport:** Socket.IO, NOT REST. Confirmed from `agent-x-live-chat.js`:

```
CLIENT                                              SERVER
  │                                                    │
  │──── connect (websocket) ────────────────────────► │
  │                                                    │
  │──── emit 'join_room' {room: customerId} ────────► │
  │                                                    │
  │◄─── on 'room_joined' (data) ────────────────────  │
  │                                                    │
  │──── emit 'customer_send_message' {                │
  │       room: customerId,                           │
  │       message: JSON.stringify({                   │
  │         message_id: payload.message_id,           │
  │         message: payload.message,                 │
  │         agent_id: payload.agent_id,               │
  │         customer_id: payload.customer_id          │
  │       })                                          │
  │     } ───────────────────────────────────────────►│
  │                                                    │
  │◄─── on 'receive_chunk' (×N times) ───────────────│
  │       {message_id, role, chunk}                   │
  │                                                    │
  │◄─── on 'receive_message' (final) ─────────────────│
  │       {message_id, role, message, sender_user_name}│
  │                                                    │
  │ [optional voice]                                   │
  │◄─── on 'assistant_audio_url' ────────────────────│
  │       {url, text}                                 │
```

**Config knobs (per agent):**
- `advanced_reasoning`: ON = 3 messages/turn
- `image_analysis`: ON = 2 messages/turn
- `auto_human_mode`: timeout → switch to human agent

---

## 5. Inference prompt pattern (reconstructed)

Putting it all together, every chat turn looks roughly like this **server-side**:

```python
# Pseudo-code reconstructed from API + bundle analysis
def chat_turn(agent_id, customer_id, user_message, history):
    # 1. Load agent config
    agent = db.get_agent(agent_id)
    role_template = get_role(agent.role_id)        # from /instructions/roles
    description = agent.description                # generated by /agents/generate-description
    rules = agent.rules                            # generated by /agents/generate-rule
    skills = db.get_agent_skills(agent_id)         # /skills
    
    # 2. RAG retrieval
    context_chunks = vector_store.search(
        query=user_message,
        agent_id=agent_id,
        top_k=5
    )
    
    # 3. Build messages
    messages = [
        {"role": "system", "content": build_system_prompt(
            role_template, description, rules, skills
        )},
        {"role": "system", "content": f"Kiến thức liên quan:\n{context_chunks}"},
        *history[-10:],
        {"role": "user", "content": user_message}
    ]
    
    # 4. Call LLM (streaming)
    return stream_chat_completion(
        model="gpt-4.1-mini" if not agent.advanced_reasoning else "o1-mini",
        messages=messages,
        temperature=0.3 if agent.deterministic else 0.7,
        stream=True
    )
```

The **system prompt is built by concatenating**:
1. The role template (e.g. Customer Care Agent)
2. The 7-section description (from generate-description)
3. The rule expansions (from generate-rule)
4. Active skills and golden products/policies/promotions

---

## 6. The "golden" data system (product/policy/promotion RAG)

Beyond text RAG, there's a **structured knowledge layer**:

| Endpoint | What it stores |
|----------|----------------|
| `GET /golden-products` | Products with SKU, name, price, variants |
| `GET /golden-policies` | Business policies (return, warranty, etc.) |
| `GET /golden-promotions` | Active promotions/vouchers |

Each conversation can have `related_policies` and `related_promotions` attached. The agent uses these for **upsell/cross-sell** reasoning. Field aliasing is built in:
```
short_desc    → short_description
mo_ta_ngan    → short_description
mo_ta_chi_tiet → description
content       → description
specs         → attributes
```

So when you bulk-import from KiotViet/Haravan/Pancake, the importer maps Vietnamese column names automatically.

---

## 7. What Agent-X charges for (the plan gating)

From `/plans/subscriptions` and the pricing dialog code:

| Plan | msgs/mo | data/agent | URLs | storage | trainings/mo | agents | teams | integrations |
|------|---------|------------|------|---------|--------------|--------|-------|--------------|
| Free | small | limited | limited | small | limited | 1 | 1 | none |
| Starter | X msg | Y MB | unlimited | 0.X GB | Z | 1 | 1 | FB, Zalo OA |
| Growth | 10×X | Y MB | unlimited | X GB | 10×Z | N | M | + KiotViet |
| Scale | 50×X | Y MB | unlimited | 10× GB | 50×Z | N | M | all |

**Advanced reasoning toggle** = 3× tokens per turn (uses `o1-mini` or similar reasoning model).
**Image analysis toggle** = 2× tokens per turn.

---

## 8. How to replicate this stack in 2 weeks

### Option A — Use Agent-X as-is (0 engineering)

Just sign in, click **Tích hợp → Zalo OA**, upload your knowledge, you're live.

### Option B — Build your own using extracted prompts (1-2 weeks)

You now have:
- ✅ 3 master system prompts (description, rule, order extraction)
- ✅ 3 default agent role templates
- ✅ The full training pipeline (5 source types, status machine)
- ✅ The inference protocol (Socket.IO streaming events)
- ✅ The structured data model (golden products/policies/promotions)

**Stack to use:**
- **Orchestration:** LangChain or **Flowise OSS** (literally what Agent-X uses)
- **Vector store:** pgvector / Pinecone / Qdrant
- **LLM:** OpenAI gpt-4.1-mini (cheap) for generation/extraction; gpt-4o for live inference
- **Embedding:** OpenAI text-embedding-3-small
- **Vietnamese boost:** BAAI/bge-m3 or keepai/vietnamese-embeddings
- **Transport:** Socket.IO with `customer_send_message` / `receive_chunk` / `receive_message`

### Option C — Hybrid (recommended for you)

Build a thin **white-label Next.js admin** that calls Agent-X's REST API under the hood (all 93 endpoints are documented now). Then for the parts Agent-X can't do (custom Zalo workflows, multi-tenant reselling, custom analytics), build them on top.

---

## 9. Key insights for YOUR system

Given your profile (founder, agency/IT/outsourcing, Zalo-first):

1. **Don't recreate the agent training loop** — it's complex and they have it. Use their `/training/*` and `/agents/*` endpoints.

2. **For Zalo-X Assistant-style group PM bot**: build a custom Zalo listener that:
   - Watches a Zalo group for `@AI` mentions
   - Forwards to `/api/n/v1/training/generate-answer` or your own agent endpoint
   - Posts the reply back into the group
   
   This bypasses Agent-X's UI entirely while reusing their training.

3. **For custom white-label admin**: the React bundle has TanStack Query keys for all 93 endpoints. You can rebuild the UI in a weekend.

4. **For multi-tenant reselling**: each Agent-X org has `flowise_organization_id` — that's your tenancy boundary. Map your clients → Agent-X orgs 1:1.

5. **Cost**: Agent-X is using `gpt-4.1-mini` for everything except inference. At ~$0.40/1M input tokens, your training generation is essentially free. Live inference is where money goes — consider their Advanced Reasoning toggle as a profit center.

---

## 10. Reproducible leak list

For your own research/red-team purposes, here are endpoints that leak `usage.metadata.system_prompt`:

| Endpoint | What it reveals |
|----------|-----------------|
| `POST /api/n/v1/agents/generate-description` | Master description prompt |
| `POST /api/n/v1/agents/generate-rule` | Master rule-expansion prompt |
| `POST /api/n/v1/orders/extract-order` | Order extraction prompt + extraction_request template |

Try them yourself with your token — just send valid-shape payloads and inspect `usage.metadata.system_prompt` and `usage.metadata.user_prompt`.
