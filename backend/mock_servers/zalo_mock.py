"""Zalo Bot Platform mock server for local development.

Simulates the Zalo Bot Platform API so the VFIC chatbot can run end-to-end
on localhost without hitting the real Zalo servers.  Serves a browser-based
chat UI at ``/`` for sending fake user messages and viewing bot replies.

Run::

    cd backend
    python -m mock_servers.zalo_mock --port 8788

The backend points at this mock by setting ``ZALO_BOT_API_BASE`` to
``http://localhost:8788`` (done automatically by ``make dev``).

Contract reproduced (see ``app/services/zalo_bot_service.py``):
  - Outbound: ``POST {base}/bot{TOKEN}/{method}`` with JSON body.
  - Inbound: Telegram-style payload POSTed to ``/webhooks/zalo``.
  - Response envelopes: ``{ok, result}`` / ``{ok, error_code, description}``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import time
import uuid

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

# ---------------------------------------------------------------------------
# Config & state
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("zalo-mock")

app = FastAPI(title="Zalo Mock Server")

BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))
WEBHOOK_URL = f"http://localhost:{BACKEND_PORT}/webhooks/zalo"
AUTO_REPLY_DELAY = float(os.environ.get("AUTO_REPLY_DELAY", "1.5"))

# In-memory conversation store: {chat_id: [event, ...]}
# Each event: {"role": "user"|"bot"|"typing"|"system", "text": ..., "ts": float}
_conversations: dict[str, list[dict]] = {}
_msg_counter = 0

# Sample replies a "user" sends back when the bot messages them.
_AUTO_REPLIES = [
    "dạ vâng, em hiểu rồi ạ",
    "cảm ơn anh/chị nhiều nhé",
    "cho em hỏi thêm một chút được không ạ",
    "em muốn biết thêm về mức lương ạ",
    "dạ, em muốn ứng tuyển vị trí này ạ",
    "ok em sẽ gửi hồ sơ sớm ạ",
    "thời gian làm việc như thế nào ạ",
    "em có thể liên hệ qua số điện thoại không ạ",
    "dạ vâng, em sẽ xem xét ạ",
    "cho em hỏi yêu cầu công việc gì ạ",
]


def _next_id() -> int:
    global _msg_counter
    _msg_counter += 1
    return _msg_counter


def _record(chat_id: str, role: str, text: str = "") -> None:
    _conversations.setdefault(chat_id, []).append({"role": role, "text": text, "ts": time.time()})


def _ts_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Auto-reply: simulate user responding after bot sends a message
# ---------------------------------------------------------------------------


async def _fire_user_reply(chat_id: str) -> None:
    """Background task: wait briefly then POST a simulated user reply
    back to the backend webhook so the full round-trip works in dev."""
    await asyncio.sleep(AUTO_REPLY_DELAY)

    reply_text = random.choice(_AUTO_REPLIES)
    payload = {
        "update_id": _next_id(),
        "message": {
            "message_id": _next_id(),
            "date": int(time.time()),
            "chat": {"id": chat_id},
            "from": {"id": chat_id, "display_name": "Mock User"},
            "text": reply_text,
        },
    }

    _record(chat_id, "user", reply_text)
    logger.info("AUTO-REPLY chat=%s  text=%s", chat_id, reply_text[:100])

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(WEBHOOK_URL, json=payload)
        resp_json = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        logger.info(
            "AUTO-REPLY WEBHOOK %s  %s",
            resp.status_code,
            json.dumps(resp_json, ensure_ascii=False)[:200],
        )
    except Exception as exc:
        logger.error("AUTO-REPLY webhook POST failed: %s", exc)
        _record(chat_id, "system", f"auto-reply error: {exc}")


# ---------------------------------------------------------------------------
# Outbound responder — what the backend calls
# ---------------------------------------------------------------------------


@app.post("/bot{token}/{method}")
async def bot_method(token: str, method: str, request: Request) -> JSONResponse:
    """Catch-all for Zalo Bot Platform methods.

    ``{token}`` is captured but ignored — any non-empty token works (the real
    platform uses it for routing; the mock accepts everything).
    """
    try:
        body = await request.json() or {}
    except Exception:
        body = {}

    chat_id = body.get("chat_id", "unknown")
    logger.info(
        "→ %s…/%s  chat=%s  body=%s",
        token[:12],
        method,
        chat_id,
        json.dumps(body, ensure_ascii=False)[:200],
    )

    # Message methods — record bot reply, return success envelope.
    if method in ("sendMessage", "sendPhoto", "sendSticker", "sendVoice"):
        reply_text = body.get("text") or body.get("caption") or ""
        _record(chat_id, "bot", reply_text)
        # Simulate user replying back after a short delay.
        asyncio.create_task(_fire_user_reply(chat_id))
        return JSONResponse(
            {
                "ok": True,
                "result": {"message_id": str(uuid.uuid4()), "date": _ts_ms()},
            }
        )

    # Typing indicator — record, return minimal envelope (no ``result``).
    if method == "sendChatAction":
        _record(chat_id, "typing")
        return JSONResponse({"ok": True})

    # Bot identity.
    if method == "getMe":
        return JSONResponse(
            {
                "ok": True,
                "result": {
                    "id": "mock-bot",
                    "account_name": "VFIC Mock Bot",
                    "account_type": "bot",
                    "can_join_groups": False,
                },
            }
        )

    # Long-polling (returns empty when webhook is active).
    if method == "getUpdates":
        return JSONResponse({"ok": True, "result": []})

    # Admin webhook methods: setWebhook, deleteWebhook, getWebhookInfo.
    return JSONResponse(
        {
            "ok": True,
            "result": {"url": body.get("url", ""), "updated_at": _ts_ms()},
        }
    )


# ---------------------------------------------------------------------------
# Inbound trigger — browser → backend webhook
# ---------------------------------------------------------------------------


@app.post("/mock/send")
async def mock_send(request: Request) -> JSONResponse:
    """Build a Telegram-style payload and POST it to the backend webhook.

    The payload shape mirrors what ``ZaloWebhookService.normalize`` expects
    (see ``app/services/webhook.py``).
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    chat_id = body.get("chat_id", "mock-user-123")
    text = body.get("text", "")
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)

    payload = {
        "update_id": _next_id(),
        "message": {
            "message_id": _next_id(),
            "date": int(time.time()),
            "chat": {"id": chat_id},
            "from": {"id": chat_id, "display_name": "Mock User"},
            "text": text,
        },
    }

    _record(chat_id, "user", text)
    logger.info("SEND chat=%s  text=%s", chat_id, text[:100])

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(WEBHOOK_URL, json=payload)
        result = resp.json()
        logger.info(
            "WEBHOOK %s  %s",
            resp.status_code,
            json.dumps(result, ensure_ascii=False)[:200],
        )
        return JSONResponse({"backend_status": resp.status_code, "backend_response": result})
    except Exception as exc:
        logger.error("webhook POST failed: %s", exc)
        _record(chat_id, "system", f"webhook error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.get("/mock/conversation/{chat_id}")
async def get_conversation(chat_id: str) -> JSONResponse:
    """Return the in-memory event list for a chat (polled by the UI)."""
    return JSONResponse(_conversations.get(chat_id, []))


@app.delete("/mock/conversation/{chat_id}")
async def clear_conversation(chat_id: str) -> JSONResponse:
    """Clear the event list for a chat."""
    _conversations.pop(chat_id, None)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Browser chat UI
# ---------------------------------------------------------------------------

HTML_PAGE = """\
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Zalo Mock</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:#f5f6f1;display:flex;flex-direction:column;height:100vh;color:#1a1a1a}
.header{background:#1a1a1a;color:#fff;padding:12px 20px;display:flex;align-items:center;gap:12px;flex-shrink:0}
.header h1{font-size:16px;font-weight:600}
.header .tag{background:#333;color:#aaa;font-size:11px;padding:2px 8px;border-radius:4px}
.controls{background:#fff;border-bottom:1px solid #ddd;padding:8px 20px;display:flex;gap:8px;align-items:center;flex-shrink:0}
.controls label{font-size:13px;color:#666}
.controls input{border:1px solid #ccc;border-radius:6px;padding:6px 10px;font-size:13px}
#chatId{width:180px}
.chat-area{flex:1;overflow-y:auto;padding:16px 20px;display:flex;flex-direction:column;gap:8px}
.msg{max-width:80%;padding:10px 14px;border-radius:12px;font-size:14px;line-height:1.5;word-wrap:break-word}
.msg.user{align-self:flex-end;background:#0068ff;color:#fff;border-bottom-right-radius:4px}
.msg.bot{align-self:flex-start;background:#fff;border:1px solid #e0e0e0;border-bottom-left-radius:4px}
.msg.typing{align-self:flex-start;background:#f0f0f0;color:#999;font-style:italic;border-bottom-left-radius:4px}
.msg.system{align-self:center;background:#fff3cd;color:#856404;font-size:12px;border:1px solid #ffc107;border-radius:6px}
.input-bar{background:#fff;border-top:1px solid #ddd;padding:10px 20px;display:flex;gap:8px;flex-shrink:0}
.input-bar input{flex:1;border:1px solid #ccc;border-radius:8px;padding:10px 14px;font-size:14px}
.input-bar button{background:#0068ff;color:#fff;border:none;border-radius:8px;padding:10px 20px;font-size:14px;font-weight:600;cursor:pointer}
.input-bar button:hover{background:#0050d4}
.input-bar button:disabled{background:#aaa;cursor:not-allowed}
.log-toggle{background:#f5f6f1;border-top:1px solid #ddd;padding:4px 20px;flex-shrink:0}
.log-toggle button{background:none;border:none;color:#666;font-size:12px;cursor:pointer;padding:4px 0}
.log-panel{background:#1a1a1a;color:#0f0;font-family:monospace;font-size:12px;padding:10px 16px;overflow-y:auto;max-height:160px;flex-shrink:0;display:none}
.log-panel.open{display:block}
.log-panel .log-line{padding:2px 0;opacity:0.8}
</style>
</head>
<body>
<div class="header">
  <h1>🤖 Zalo Mock</h1>
  <span class="tag">localhost</span>
  <span class="tag">dev only</span>
</div>
<div class="controls">
  <label for="chatId">ID cuộc chat:</label>
  <input id="chatId" value="mock-user-123" placeholder="chat_id">
  <button onclick="clearChat()" style="background:none;border:1px solid #ccc;border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer">Xóa</button>
</div>
<div class="chat-area" id="chatArea"></div>
<div class="input-bar">
  <input id="msgInput" placeholder="Nhập tin nhắn…" onkeydown="if(event.key==='Enter')send()">
  <button id="sendBtn" onclick="send()">Gửi</button>
</div>
<div class="log-toggle"><button onclick="toggleLog()">📋 Log</button></div>
<div class="log-panel" id="logPanel"></div>

<script>
const chatArea = document.getElementById('chatArea');
const chatIdInput = document.getElementById('chatId');
const msgInput = document.getElementById('msgInput');
const logPanel = document.getElementById('logPanel');
let lastCount = 0;

function esc(s){ const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }

async function poll(){
  const cid = chatIdInput.value.trim() || 'mock-user-123';
  try {
    const r = await fetch('/mock/conversation/' + encodeURIComponent(cid));
    const events = await r.json();
    if(events.length > lastCount){
      const fresh = events.slice(lastCount);
      fresh.forEach(e => {
        if(e.role === 'user') appendMsg('user', e.text);
        else if(e.role === 'bot') appendMsg('bot', e.text);
        else if(e.role === 'typing') appendMsg('typing', 'Đang nhập…');
        else if(e.role === 'system') appendMsg('system', e.text);
      });
      lastCount = events.length;
    }
  } catch(e){}
}

function appendMsg(role, text){
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  if(role === 'user') div.innerHTML = '👤 ' + esc(text);
  else if(role === 'bot') div.innerHTML = '🤖 ' + esc(text);
  else div.textContent = text;
  chatArea.appendChild(div);
  chatArea.scrollTop = chatArea.scrollHeight;
}

async function send(){
  const text = msgInput.value.trim();
  if(!text) return;
  const cid = chatIdInput.value.trim() || 'mock-user-123';
  msgInput.value = '';
  msgInput.disabled = true;
  document.getElementById('sendBtn').disabled = true;
  try {
    const r = await fetch('/mock/send', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({chat_id: cid, text}),
    });
    const data = await r.json();
    if(data.error) appendMsg('system', 'Lỗi: ' + data.error);
  } catch(e){
    appendMsg('system', 'Lỗi kết nối: ' + e.message);
  }
  msgInput.disabled = false;
  document.getElementById('sendBtn').disabled = false;
  msgInput.focus();
}

async function clearChat(){
  const cid = chatIdInput.value.trim() || 'mock-user-123';
  await fetch('/mock/conversation/' + encodeURIComponent(cid), {method:'DELETE'});
  chatArea.innerHTML = '';
  lastCount = 0;
}

function toggleLog(){
  logPanel.classList.toggle('open');
}

// Reset event count when chat_id changes.
chatIdInput.addEventListener('change', () => { chatArea.innerHTML = ''; lastCount = 0; });

// Poll every 1s.
setInterval(poll, 1000);
poll();
msgInput.focus();
</script>
</body>
</html>
"""


@app.get("/")
async def index() -> HTMLResponse:
    """Serve the browser-based chat UI."""
    return HTMLResponse(HTML_PAGE)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="Zalo Bot Platform mock server")
    parser.add_argument("--port", type=int, default=8788, help="Port to bind (default: 8788)")
    parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="Host to bind (default: 127.0.0.1)"
    )
    args = parser.parse_args()

    logger.info("Zalo Mock starting on http://%s:%d", args.host, args.port)
    logger.info("Backend webhook target: %s", WEBHOOK_URL)
    uvicorn.run(app, host=args.host, port=args.port)
