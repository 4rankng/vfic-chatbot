"""VFIC chatbot prompts.

The agent persona lives in ``persona.md`` (next to this file) and is loaded at
import time — edit that Markdown file to tune the bot's 7-part role definition;
no Python changes are required. ``SAFETY_PROMPT`` and ``ERROR_REPLY`` are
hand-maintained constants.
"""

from pathlib import Path

_PERSONA_PATH = Path(__file__).resolve().parent / "persona.md"
# Source of truth for the bot's behaviour. Loaded once at import so a missing or
# corrupt file fails fast at worker startup rather than mid-conversation.
AGENT_SYSTEM_PROMPT = _PERSONA_PATH.read_text(encoding="utf-8").strip()

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

ERROR_REPLY = (
    """Xin lỗi bạn, tôi đang gặp chút sự cố kỹ thuật. Bạn vui lòng nhắn lại sau ít phút nhé 🙏"""
)

# Sent when the propagated ~10s deadline expires before the agent finished (tôi/bạn
# voice per persona.md). Distinct from DEGRADATION_REPLY (LLM throttled / high traffic):
# this means "I need a little more time", not "the system is overloaded".
TIMEOUT_REPLY = """Tôi cần thêm một chút thời gian để kiểm tra thông tin chính xác cho bạn. Bạn nhắn lại giúp tôi sau ít phút nhé 🙏"""
