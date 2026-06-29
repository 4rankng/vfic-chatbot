"""Locust load-test rig for the VFIC chatbot webhook endpoint.

Drives POST /webhooks/zalo at configurable message rates to measure
end-to-end latency, error rates, and queue saturation under load.

Usage (from the backend/ directory):

    # Install locust if needed
    pip install locust

    # Point at the dev/target host (use http://host.docker.internal for remote droplet)
    export WEBHOOK_BASE_URL=http://localhost:8000
    export ZALO_BOT_WEBHOOK_SECRET=   # set if target requires auth (empty for dev)

    # Run headless
    locust -f scripts/loadtest/locustfile.py \\
        --host $WEBHOOK_BASE_URL \\
        --headless -u 50 -r 5 -t 3m

    # Or use the web UI at http://localhost:8089
    locust -f scripts/loadtest/locustfile.py --host $WEBHOOK_BASE_URL
"""

from __future__ import annotations

import json
import os
import random
import time
import uuid

from locust import HttpUser, task

WEBHOOK_BASE_URL = os.environ.get("WEBHOOK_BASE_URL", "http://localhost:8000")
WEBHOOK_SECRET = os.environ.get("ZALO_BOT_WEBHOOK_SECRET", "")

# Realistic Vietnamese recruitment queries for load testing.
SAMPLE_QUERIES = [
    "chào em, cho em hỏi về công việc đang tuyển dụng",
    "xin chào, em muốn biết thông tin tuyển dụng",
    "em chào ạ, công ty đang tuyển dụng vị trí gì ạ",
    "cho em hỏi lương và chế độ đãi ngò chưa ạ",
    "em muốn ứng tuyển công việc, cho em hỏi yêu cầu",
    "xin chào, em thấy bài tuyển dụng và muốn tìm hiểu thêm",
    "cho em hỏi thời gian làm việc và ngày nghỉ như thế nào",
    "em cần thông tin liên hệ để nộp hồ sơ ạ",
    "chào anh/chị, em hỏi về quy trình phỏng vấn ạ",
    "cho em hỏi công việc này cần kinh nghiệm gì không",
    "em muốn biết môi trường làm việc như thế nào ạ",
    "xin lỗi, em có thể hỏi về mức lương không ạ",
    "em đang tìm kiếm công việc, anh/chị có thể tư vấn không",
    "cho em hỏi hồ sơ ứng tuyển cần những gì ạ",
]


class ChatbotWebhookUser(HttpUser):
    """Simulates Zalo users sending messages to the bot webhook."""

    # Each simulated user gets a unique zalo_chat_id so dedup never triggers.
    _user_counter = 0

    def on_start(self) -> None:
        ChatbotWebhookUser._user_counter += 1
        self.zalo_chat_id = f"loadtest-{ChatbotWebhookUser._user_counter}-{uuid.uuid4().hex[:8]}"

    def _build_payload(self, text: str | None = None) -> dict:
        """Build a Zalo Bot Platform receive-event payload."""
        return {
            "update_id": int(time.time() * 1000),
            "message": {
                "message_id": f"msg-{uuid.uuid4().hex[:12]}",
                "date": int(time.time()),
                "chat": {"id": self.zalo_chat_id},
                "from": {"id": f"user-{uuid.uuid4().hex[:8]}", "name": "Load Test User"},
                "text": text or random.choice(SAMPLE_QUERIES),
            },
        }

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if WEBHOOK_SECRET:
            headers["X-Bot-Api-Secret-Token"] = WEBHOOK_SECRET
        return headers

    @task
    def send_message(self) -> None:
        """Send one simulated Zalo message to the webhook."""
        payload = self._build_payload()
        with self.client.post(
            "/webhooks/zalo",
            json=payload,
            headers=self._headers(),
            catch_response=True,
            name="/webhooks/zalo",
        ) as response:
            if response.status_code != 200:
                response.failure()
