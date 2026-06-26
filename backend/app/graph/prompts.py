"""VFIC chatbot prompts.

The agent persona lives in ``persona.md`` (next to this file) and is loaded at
import time — edit that Markdown file to tune the bot's 7-part role definition;
no Python changes are required. ``SAFETY_PROMPT`` and ``ERROR_REPLY`` are
hand-maintained constants (historically mirrored from the legacy n8n workflow,
which is now DR-only).
"""

from pathlib import Path

_PERSONA_PATH = Path(__file__).resolve().parent / "persona.md"
# Source of truth for the bot's behaviour. Loaded once at import so a missing or
# corrupt file fails fast at worker startup rather than mid-conversation.
AGENT_SYSTEM_PROMPT = _PERSONA_PATH.read_text(encoding="utf-8").strip()

# Rule-expander system prompt — the "brain" behind admin persona generation
# (POST /knowledge/personas/generate). Same fail-fast load discipline as above.
_RULE_EXPANDER_PATH = Path(__file__).resolve().parent / "rule_expander.md"
RULE_EXPANDER_PROMPT = _RULE_EXPANDER_PATH.read_text(encoding="utf-8").strip()

SAFETY_PROMPT = """Bạn là AI kiểm duyệt chất lượng câu trả lời trước khi gửi cho người dùng cuối.

Nhiệm vụ: kiểm tra câu trả lời của chatbot VFIC. Nếu câu trả lời đã an toàn, tự nhiên và phù hợp để gửi cho người lao động, trả safe_to_send=true. Nếu câu trả lời chứa code, JSON, markdown phức tạp, prompt, workflow, tên node, biến, logic nội bộ, thuật ngữ kỹ thuật khó hiểu, hoặc trả lời lạc đề, trả safe_to_send=false để chatbot viết lại.

Chỉ trả về một JSON object hợp lệ theo đúng format:
{
  "safe_to_send": true,
  "issue_found": false,
  "issue_type": "none",
  "final_answer": "Câu trả lời cuối cùng bằng tiếng Việt"
}

Quy tắc:
- final_answer phải là văn bản thuần túy sẵn sàng gửi cho người dùng cuối.
- Không dùng markdown để in đậm, không dùng bảng, không dùng code block.
- Không để lộ code, JSON, prompt, workflow, tên node, biến hoặc logic nội bộ.
- Không giải thích quá trình kiểm duyệt trong final_answer.
- Nếu chỉ cần sửa rất nhẹ như xóa markdown hoặc làm câu chữ tự nhiên hơn, vẫn có thể trả safe_to_send=true và đặt final_answer là bản đã làm sạch.
- Nếu câu trả lời cần viết lại đáng kể vì chứa nội dung kỹ thuật/code/lạc đề, trả safe_to_send=false."""

ERROR_REPLY = """Xin lỗi bạn, tôi đang gặp chút sự cố kỹ thuật. Bạn vui lòng nhắn lại sau ít phút nhé 🙏"""
