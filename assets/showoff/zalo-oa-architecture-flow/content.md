# Architecture Flow — Recruiter → Frontend → Backend → Zalo OA → Zalo Users

*Bilingual showcase content (Vietnamese / English). Drives the HTML build.*
*System: **Ting Ting** — VFIC's AI recruiting concierge on Zalo. All technical
details below are read directly from the ChatBot source code.*

---

## Section 1 — Hero (#hero)

> **VI:** Từ một tin nhắn Zalo — đến một ứng viên tiềm năng — trong tích tắc.
> **EN:** From a single Zalo message — to a potential hire — in a heartbeat.

Ting Ting là trợ lý tuyển dụng AI chạy trên **Zalo Official Account (OA)**,
nối hàng triệu người dùng Zalo trực tiếp với nhà tuyển dụng. Năm lớp —
**Nhà tuyển dụng · Giao diện · Backend · Zalo OA · Người dùng Zalo** —
hoạt động như một dây chuyền tin nhắn hai chiều, tức thì, an toàn.

Ting Ting is an AI recruiting assistant on the **Zalo Official Account**,
connecting millions of Zalo users directly with recruiters. Five layers —
**Recruiter · Frontend · Backend · Zalo OA · Zalo users** — operate as one
bidirectional, real-time, secure messaging pipeline.

**At a glance / Tổng quan**
- Webhook đáp dưới **1 giây** · Acknowledges webhooks in **< 1 s**
- **Kênh kép**: Bot Platform + Official Account · **Dual-channel** architecture
- Bộ não **MiniMax M2.7** + embeddings Gemini · **MiniMax M2.7** brain
- Đẩy thời gian thực qua **Socket.IO** · **Socket.IO** realtime fan-out
- **5 chế độ** hội thoại (BOT / SEMI_AUTO / HUMAN / …) · **5 conversation modes**

---

## Section 2 — The Recruiter's Cockpit / Buồng lái tuyển dụng (#recruiter-frontend)

> **VI:** Nơi nhà tuyển dụng tiếp quản cuộc trò chuyện.
> **EN:** Where the recruiter takes the wheel.

Giao diện là một **React 19 + react-admin** single-page app (Tailwind v4,
Shadcn UI), tiếng Việt hoàn toàn. Hộp thư thư_file `ConversationList`,
luồng tin `ChatThread`, và bảng ngữ cảnh `ConversationContextPanel`
(hồ sơ ứng viên) chia sẻ một cửa sổ duy nhất.

The frontend is a **React 19 + react-admin** SPA (Tailwind v4, Shadcn UI),
Vietnamese-only. The inbox `ConversationList`, the live `ChatThread`, and the
`ConversationContextPanel` (candidate lead profile) share one workspace.

**Realtime:** Mỗi trình duyệt giữ một socket Socket.IO, được xác thực bằng JWT
và gom vào các *room* `conv:{id}` / `user:{id}`. Hook `useConversationRealtime`
nhận sự kiện → cập nhật `messageStore` → `ChatThread` vẽ lại tức thì. Không có
thăm dò (polling).

**Realtime:** Each browser holds one Socket.IO socket, JWT-authenticated and
roomed into `conv:{id}` / `user:{id}`. The `useConversationRealtime` hook
receives events → updates `messageStore` → the `ChatThread` re-renders live.
No polling.

**Human takeover / Tiếp nhận bởi người:**
- `take-over` → chế độ **HUMAN**, chuyên trách một recruiter.
- `release` → đẩy lại các tin chưa trả lời vào hàng đợi bot.
- `semi-auto` → bot và người cùng can thiệp.
- Badge **needs-attention** đếm các hội thoại chưa trả lời.

---

## Section 3 — The Backend Brain / Bộ não backend (#backend-brain)

> **VI:** FastAPI + một pipeline kiểu LangGraph — suy nghĩ, kiểm duyệt, rồi mới gửi.
> **EN:** FastAPI + a LangGraph-style pipeline — think, vet, then send.

Mỗi lượt bot chạy qua một đường ống các "node" (hàm đặt tên theo node),
`run_turn`, so khớp 1:1 với topo LangGraph:

Every bot turn runs through a node-named pipeline, `run_turn`, mirroring the
LangGraph topology 1:1:

1. **load_conversation_state** — nạp hội thoại + 16 tin gần nhất.
2. **typing** — nhịp typing 4 giây giữ trạng thái "đang gõ" trên Zalo.
3. **agent** — **MiniMax M2.7** tool-calling: tìm kiếm kiến thức (RAG,
   embeddings Gemini 3072-chiều), thu thập lead, trả lời theo persona.
4. **fast_safety_filter** → nếu dấu hiệu rủi ro → **llm_safety_check**
   (viết lại 1 lần hoặc fallback an toàn).
5. **pre_send_guard** — *kiểm tra quyền sở hữu lại* sau khi sinh: nếu recruiter
   đã tiếp nhận giữa chừng → tin bị **SUPPRESSED** (không gửi).
6. **send_message** → **log_sent** (+ trích xuất lead/bộ nhớ chỉ khi đã gửi thật).

**Key invariant:** Quyền sở hữu được kiểm tra **hai lần** — trước và sau khi
LLM sinh câu trả lời — để không bao giờ gửi thay người khi recruiter đã tiếp quản.

**Key invariant:** Ownership is checked **twice** — before and after the LLM
generates the reply — so the bot never speaks over a recruiter who just took over.

`GraphDeps` tiêm LLM/embedder/Zalo/DB → toàn bộ nhánh safety/ownership/suppress
chạy unit-test được bằng fake, không cần API key.

---

## Section 4 — The Zalo OA Bridge / Cầu nối Zalo OA (#zalo-oa-bridge)

> **VI:** Một facade duy nhất — tự chọn kênh Bot hay OA theo từng hội thoại.
> **EN:** One facade — picks Bot or OA per conversation.

`ZaloChannelSender` nhìn `conv.zalo_channel`: nếu `"oa"` → dùng `ZaloOASender`,
ngược lại → `ZaloBotSender`. Toàn bộ đồ thị agent vẫn **channel-agnostic**.

`ZaloChannelSender` inspects `conv.zalo_channel`: `"oa"` → `ZaloOASender`,
otherwise → `ZaloBotSender`. The entire agent graph stays **channel-agnostic**.

**Gửi qua OA / Sending via OA** — `POST {OA_BASE}/v3.0/oa/message/cs`:
- Header: `access_token: <OA access token>`
- Body: `{ "recipient": { "user_id": chat_id }, "message": { "text": chunk } }`
- Tin dài được **chia khúc** (giới hạn 1–2000 ký tự/khúc).

**Token management / Quản lý token:** access token + refresh token được nhập thủ
công bởi admin, **mã hóa khi lưu**, hiển thị dạng che (`•••••`) cho mọi vai trò,
và có audit trail cho mỗi lần đổi tên khóa. (Luồng OAuth QR-scan từng tồn tại
nhưng đã được dỡ bỏ — entry thủ công là đường chính thức.)

---

## Section 5 — The Webhook Conduit / Đường ống webhook hai đầu (#webhook-conduit)

> **VI:** Hai đầu vào, hai cơ chế ký — và một chuỗi bảo vệ chạy dưới 1 giây.
> **EN:** Two endpoints, two signature schemes — and a sub-second guard chain.

**Hai endpoint / Two endpoints**
- `POST /webhooks/zalo/chatbot` — **Bot Platform**: secret chung
  `X-Bot-Api-Secret-Token` (echo do Zalo gửi lại).
- `POST /webhooks/zalo/oa` — **Official Account**: xác minh chữ ký
  `X-ZEvent-Signature` = `sha256(appId + data + timestamp + OAsecretKey)`.

Môi trường không phải dev mà chưa cấu hình secret → trả **503** (từ chối mù),
không bao giờ chấp nhận inbound chưa xác thực. Zalo sẽ thử lại khi nhận 503.

Non-dev with no secret configured → **503** (refuse blind), never accepting
unverified inbound. Zalo retries on 503.

**Chuỗi bảo vệ đồng bộ (< 1s) / Synchronous guard chain (< 1s)** — chạy trong
process web trước khi đưa vào hàng đợi:

`normalize → dedup (msg_hash) → ensure conversation → record_inbound
→ run_start_guard → acquire_lock → typing → enqueue RQ`

- **run_start_guard**: HUMAN / SEMI_AUTO-active / CLOSED → bot bị "starve"
  (không khởi lượt).
- **acquire_lock**: mutex mỗi chat — chỉ một lượt chạy tại một thời điểm.
- Trả `200 queued`, hoặc `503 enqueue_failed` (Redis xuống → Zalo retry).

---

## Section 6 — End-to-End Lifecycle / Vòng đời hai chiều (#e2e-flow)

> **VI:** Cùng một đường ống — chảy theo hai chiều.
> **EN:** One pipeline — flowing in two directions.

**Hướng ứng viên → recruiter (Inbound):**
Người dùng Zalo gõ tin → Zalo đẩy vào webhook OA → xác minh chữ ký →
chuỗi guard → `record_inbound` → enqueue RQ → `run_turn` (agent → safety →
ownership) → `ZaloOASender.send_message` trả lời lại → Socket.IO báo recruiter.

**Hướng recruiter → ứng viên (Outbound):**
Recruiter `take-over` → gõ trả lời → `POST /conversations/{id}/messages` →
kiểm tra JWT + ownership + chế độ → `deliver_recruiter_message` lưu tin
(lưu cả khi gửi thất bại, làm audit trail) → `ZaloChannelSender` chọn OA sender
→ `oa/message/cs` → tin tới máy ứng viên.

**Năm bất biến của hệ thống / Five system invariants**
1. **Sub-second ack** — webhook đáp < 1s, việc nặng sang RQ.
2. **Signature-verified** — mọi inbound đều xác thực, hoặc 503.
3. **Ownership-safe** — kiểm tra quyền hai lần; SUPPRESSED nếu recruiter tiếp quản.
4. **Idempotent** — dedup theo `msg_hash`; trùng lặp bị bỏ qua.
5. **Channel-aware** — Bot hay OA, cùng một đồ thị agent.

Worker reconcile quét các hội thoại chưa trả lời và thử giao lại — đảm bảo không
tin nhắn nào bị bỏ rơi giữa hai thế giới.

---

## References / Tài liệu tham khảo

- Zalo Official Account OpenAPI — https://developers.zalo.me/docs/api/official-account-api-230
- Zalo OA webhook: người dùng gửi tin nhắn (`user_send_text`) — https://developers.zalo.me/docs/api/official-account-api/webhook/su-kien-nguoi-dung-gui-tin-nhan-post-3720
- X-ZEvent-Signature verification (`sha256(appId + data + timeStamp + OAsecretKey)`) — https://developers.zalo.me/community/detail/f62243c57f8096decf91
- Zalo OA webhook: OA gửi tin cho người dùng — https://developers.zalo.me/docs/api/official-account-api/webhook/su-kien-official-account-gui-tin-nhan-cho-nguoi-dung-post-3650
- FastAPI — https://fastapi.tiangolo.com/
- LangGraph — https://langchain-ai.github.io/langgraph/
- MiniMax M-series LLM — https://www.minimaxi.com/
- Socket.IO — https://socket.io/docs/v4/
- react-admin — https://marmelab.com/react-admin/
- Source: ChatBot backend (`app/api/webhooks.py`, `app/services/webhook.py`,
  `app/services/zalo_sender.py`, `app/services/zalo_oa_service.py`,
  `app/api/conversations.py`, `app/graph/runner.py`, `app/realtime/socketio.py`)
