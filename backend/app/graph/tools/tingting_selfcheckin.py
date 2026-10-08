"""The TingTing self-check-in toggle tools: one egress site, server-side flow state.

Mirrors the reset flow (``app.graph.tools.tingting_api``): the workflow spans
turns (verify identity → OTP → code → update) but an agent turn's message list
does not, so every cross-turn secret lives in the shared ``TingtingFlowStore``
under its own keys — ``sc_session_id`` (the OTP session), ``sc_assignments``
(the employee's eligible project id/name pairs, for the one-question-per-turn
project ask) and ``sc_action_token`` (the verified-update token). Nothing from
that store ever reaches the prompt or a reply: the model owns only the phone,
the 6-digit code, the chosen project id and the enable direction.

The toggle endpoints are the payroll side's ``/api/v1/integration/self-checkin/*``
trio; assignments data (radii, gates, shift windows) is server-side routing
data and is never echoed raw — the tool surfaces project NAMES only, and only
to ask which project to toggle.
"""

from __future__ import annotations

import logging
from typing import Any

from app.graph.ports import GraphRetrievalPort
from app.graph.tools.tingting_api import (
    _NO_PHONE,
    _UNREADABLE,
    _ok_payload,
    _otp_failure_text,
    tingting_state_text,
)

logger = logging.getLogger(__name__)

# The self-check-in toggle API's read path trio, named once: the guide and the
# tool schemas all quote these paths.
SC_OTP_PATH = "/api/v1/integration/self-checkin/otp"
SC_VERIFY_PATH = "/api/v1/integration/self-checkin/verify"
SC_UPDATE_PATH = "/api/v1/integration/self-checkin/update"
SC_STATUS_PATH = "/api/v1/integration/self-checkin/status"

_NOT_VERIFIED = (
    "Số điện thoại này chưa được xác minh danh tính. Hãy gọi verify_tingting_identity với "
    "họ tên/CCCD mà nhân viên đã cung cấp và chỉ gọi tool này khi tool trả về ĐÃ XÁC MINH."
)
_NO_OTP_SESSION = (
    "Chưa có phiên OTP tự chấm công còn hiệu lực cho số điện thoại này. Hãy gọi "
    "send_self_checkin_otp để gửi mã mới, rồi xin mã 6 số mà nhân viên nhận được."
)
_NO_ACTION_TOKEN = (
    "Chưa xác thực được mã OTP cho số điện thoại này nên chưa thể bật/tắt tự chấm công. "
    "Hãy gọi send_self_checkin_otp rồi confirm_self_checkin_otp trước."
)
_NO_PROJECT = (
    "Thiếu mã dự án (project_id). Hãy lấy project_id đúng như send_self_checkin_otp đã "
    "liệt kê cho người dùng, rồi gọi lại tool."
)
_NO_ELIGIBLE_PROJECT = (
    "Hồ sơ này chưa thuộc dự án nào hỗ trợ bật/tắt tự chấm công qua Zalo. Nói nhân viên "
    "liên hệ quản lý trực tiếp để được hỗ trợ, và DỪNG flow — không xin mã OTP, không gọi "
    "update_self_checkin."
)
_PROJECT_NOT_LISTED = (
    "project_id không nằm trong danh sách dự án mà tool OTP đã liệt kê cho hồ sơ này. "
    "Hãy dùng đúng project_id đã lưu; không tự nghĩ ra dự án khác."
)


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _stored_assignments(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The eligible projects the OTP turn stored, with their toggle state."""
    raw = state.get("sc_assignments")
    if not isinstance(raw, list):
        return []
    pairs: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        project_id = str(item.get("project_id") or "").strip()
        if not project_id:
            continue
        pairs.append(
            {
                "project_id": project_id,
                "project_name": str(item.get("project_name") or project_id).strip(),
                "check_in_enabled": bool(item.get("check_in_enabled")),
            }
        )
    return pairs


def _state_text(enabled: bool) -> str:
    return "đang BẬT" if enabled else "đang TẮT"


def _project_state_line(item: dict[str, Any]) -> str:
    return f"{item['project_name']} — tự chấm công {_state_text(item['check_in_enabled'])}"


def render_project_menu(assignments: list[dict[str, str]]) -> str:
    """The one project question the model may ask — names only, never raw data."""
    names = " / ".join(item["project_name"] for item in assignments)
    return (
        f"Hồ sơ này thuộc nhiều dự án: {names}. Hỏi người dùng muốn bật/tắt tự chấm công "
        "cho dự án nào (một câu, dùng đúng tên dự án trên)."
    )


async def send_self_checkin_otp(retrieval: GraphRetrievalPort, *, phone: str) -> str:
    """Send the toggle-flow OTP for a verified phone and store session + projects."""
    clean_phone = (phone or "").strip()
    if not clean_phone:
        return _NO_PHONE
    state = await retrieval.tingting_flow_state(clean_phone)
    if not state.get("verified") and not await retrieval.tingting_identity_verified(clean_phone):
        return _NOT_VERIFIED
    outcome = await retrieval.call_tingting_api(
        method="POST", path=SC_OTP_PATH, params={"phone": clean_phone}
    )
    if outcome.state == "duplicate_request":
        return (
            "Mã xác minh vừa được gửi cho số này trong ít giây trước. Nói nhân viên kiểm tra Zalo "
            "và dùng mã 6 số vừa nhận; nếu chưa nhận được thì chờ khoảng 1 phút rồi gọi lại tool này."
        )
    if outcome.state != "ok":
        return tingting_state_text(outcome)
    data = _ok_payload(outcome)
    if data is None:
        return _UNREADABLE
    if data.get("found") is False:
        return (
            "Không có duy nhất một tài khoản với số điện thoại này. Hỏi lại số điện thoại đã "
            "đăng ký với công ty."
        )
    if data.get("otp_sent") is not True:
        return _otp_failure_text(data)
    session_id = str(data.get("session_id") or "")
    if not session_id:
        return _UNREADABLE
    assignments = _stored_assignments({"sc_assignments": data.get("assignments")})
    if not assignments:
        # Payroll verified the phone but found no active assignment in a
        # supported project — the toggle cannot apply to this profile. Stop
        # here rather than drive to an update that payroll must refuse.
        return _NO_ELIGIBLE_PROJECT
    await retrieval.save_tingting_flow_state(
        clean_phone,
        {"sc_session_id": session_id, "sc_assignments": assignments},
    )
    lines = [
        "Đã gửi mã xác minh 6 số qua Zalo tới số điện thoại này.",
        "Tình trạng hiện tại: " + "; ".join(_project_state_line(a) for a in assignments) + ".",
    ]
    if len(assignments) > 1:
        lines.append(render_project_menu(assignments))
    lines.append(
        "Hỏi mã 6 số nhân viên nhận được, rồi gọi confirm_self_checkin_otp(phone, code). "
        "Không hỏi lại số điện thoại và không đọc mã định danh phiên cho người dùng."
    )
    return "\n".join(lines)


async def confirm_self_checkin_otp(
    retrieval: GraphRetrievalPort, *, phone: str, code: str
) -> str:
    """Verify the employee's 6-digit code and store the self-check-in action token."""
    clean_phone = (phone or "").strip()
    if not clean_phone:
        return _NO_PHONE
    state = await retrieval.tingting_flow_state(clean_phone)
    session_id = str(state.get("sc_session_id") or "")
    if not session_id:
        return _NO_OTP_SESSION
    clean_code = _digits(code)
    if len(clean_code) != 6:
        return (
            "Mã xác minh phải là đúng 6 chữ số. Hãy hỏi lại mã mà nhân viên nhận được trong Zalo."
        )
    outcome = await retrieval.call_tingting_api(
        method="POST", path=SC_VERIFY_PATH, params={"session_id": session_id, "code": clean_code}
    )
    if outcome.state == "duplicate_request":
        return (
            "Mã này vừa được kiểm tra trong ít giây trước. Hãy hỏi lại mã nhân viên nhận được; nếu "
            "vẫn là mã cũ thì chờ khoảng 1 phút rồi thử lại, hoặc gọi send_self_checkin_otp để gửi mã mới."
        )
    if outcome.state != "ok":
        if outcome.state == "error" and outcome.status_code == 401:
            # A wrong or expired code keeps the session: the same session accepts a
            # retry, and a fresh code needs a fresh send.
            return (
                "Mã 6 số không đúng hoặc đã hết hạn (phiên vẫn còn trong ít phút). Hỏi lại mã trong "
                "Zalo; nếu nhân viên không nhận được mã mới thì gọi send_self_checkin_otp để gửi lại."
            )
        if outcome.state == "error" and outcome.status_code == 400:
            return "Mã hoặc phiên không hợp lệ. Hỏi lại đúng mã 6 số mà nhân viên nhận được."
        return tingting_state_text(outcome)
    data = _ok_payload(outcome)
    if data is None:
        return _UNREADABLE
    if data.get("verified") is not True:
        return (
            "Mã 6 số không đúng hoặc đã hết hạn. Hỏi lại mã trong Zalo; cần mã mới thì gọi "
            "send_self_checkin_otp để gửi lại."
        )
    action_token = str(data.get("action_token") or "")
    if not action_token:
        return _UNREADABLE
    await retrieval.save_tingting_flow_state(clean_phone, {"sc_action_token": action_token})
    # The OTP landed on the registered number — 30 days of identity memory.
    await retrieval.mark_tingting_identity_verified(clean_phone)
    return (
        "Mã đúng. Bây giờ gọi update_self_checkin(phone, project_id, enable) — "
        "project_id là dự án người dùng đã chọn (hoặc dự án duy nhất tool OTP đã liệt kê), "
        "enable=true để BẬT tự chấm công, enable=false để TẮT. Không xin thêm thông tin nào."
    )


def _effective_date_text(raw: Any) -> str:
    """``YYYY-MM-DD`` (or any dotted/slashed variant) read as ``DD/MM``."""
    parts = [p for p in str(raw or "").replace("/", "-").split("-") if p]
    if len(parts) == 3:
        day, month = parts[2], parts[1]
        if day.isdigit() and month.isdigit():
            return f"{int(day):02d}/{int(month):02d}"
    return str(raw or "").strip()


def render_self_checkin_verdict(data: dict[str, Any]) -> str:
    """The Vietnamese verdict the model relays verbatim — never the raw payload.

    Shapes the payroll verdict (kind/immediate/effective_from/
    cancelled_pending_enable) into the operator-approved phrasings: a same-month
    enable is immediate ("đã bật ... cả tháng tính tự chấm công"), a day-9+
    enable and every disable are deferred to the effective date, and a disable
    always carries the keep-working reassurance.
    """
    kind = str(data.get("kind") or "").strip().lower()
    immediate = data.get("immediate") is True
    date = _effective_date_text(data.get("effective_from"))
    if kind == "enable":
        if immediate:
            head = f"Đã BẬT tự chấm công từ ngày {date}, cả tháng tính tự chấm công."
        else:
            head = f"Tự chấm công SẼ BẬT từ ngày {date} (đầu tháng tới)."
    else:
        head = f"Tự chấm công SẼ TẮT từ ngày {date}; trước đó vẫn chấm công bình thường."
    if data.get("cancelled_pending_enable") is True:
        head += " Yêu cầu bật đang chờ trước đó đã được hủy."
    return head


async def update_self_checkin(
    retrieval: GraphRetrievalPort, *, phone: str, project_id: str, enable: bool
) -> str:
    """Consume the stored action token and relay the toggle verdict in Vietnamese."""
    clean_phone = (phone or "").strip()
    if not clean_phone:
        return _NO_PHONE
    state = await retrieval.tingting_flow_state(clean_phone)
    action_token = str(state.get("sc_action_token") or "")
    if not action_token:
        return _NO_ACTION_TOKEN
    assignments = _stored_assignments(state)
    if not assignments:
        return _NO_ELIGIBLE_PROJECT
    clean_project = str(project_id or "").strip()
    if not clean_project:
        if len(assignments) == 1:
            # One eligible project and the model omitted it: fill it rather than
            # stalling the flow with a question nobody needs to answer.
            clean_project = assignments[0]["project_id"]
        else:
            return _NO_PROJECT
    # Payroll binds project_id as a number and enable as a boolean, so the
    # egress payload must carry native JSON types — the string forms 400 at
    # Go's binding no matter how correct the values are. The model may pass
    # the project NAME (candidates answer in names); map it to the stored id
    # before the type conversion rather than refusing the whole turn.
    matched = [item for item in assignments if item["project_id"] == clean_project]
    if not matched:
        matched = [
            item
            for item in assignments
            if item["project_name"].strip().lower() == clean_project.lower()
        ]
        if not matched:
            return _PROJECT_NOT_LISTED
    try:
        project_id_num = int(matched[0]["project_id"])
    except ValueError:
        return _PROJECT_NOT_LISTED
    # Ask payroll for the CURRENT state before mutating: a toggle that matches
    # reality is answered here (no update, no error to relay). A failed status
    # read is best-effort — fall through to the update and let it decide.
    status_outcome = await retrieval.call_tingting_api(
        method="POST", path=SC_STATUS_PATH, params={"action_token": action_token}
    )
    if status_outcome.state == "ok":
        status_data = _ok_payload(status_outcome)
        items = (status_data or {}).get("assignments")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict) or item.get("project_id") != project_id_num:
                    continue
                on_now = item.get("check_in_enabled") is True
                pending = item.get("pending_change") or {}
                pending_type = str(pending.get("type") or "").strip()
                pending_date = _effective_date_text(pending.get("effective_from"))
                will_be_on = on_now or (pending_type == "enable")
                will_date = pending_date or _effective_date_text(item.get("check_in_start_date"))
                if enable and will_be_on:
                    if pending_type == "enable":
                        return f"Tự chấm công SẼ BẬT từ ngày {pending_date} rồi, không cần bật lại."
                    return (
                        f"Tự chấm công của bạn đang BẬT"
                        + (f" (từ ngày {will_date})" if will_date else "")
                        + ", không cần bật lại."
                    )
                if not enable and not will_be_on:
                    return "Tự chấm công của bạn đang TẮT, không cần tắt lại."
                if not enable and pending_type == "disable":
                    return f"Tự chấm công SẼ TẮT từ ngày {pending_date} rồi, không cần tắt lại."
                break
    outcome = await retrieval.call_tingting_api(
        method="POST",
        path=SC_UPDATE_PATH,
        params={
            "action_token": action_token,
            "project_id": project_id_num,
            "enable": bool(enable),
        },
    )
    if outcome.state != "ok":
        if outcome.state == "error" and outcome.status_code == 401:
            await retrieval.clear_tingting_flow_state(clean_phone)
            return (
                "Phiên xác thực đã hết hiệu lực nên chưa bật/tắt được tự chấm công. Hãy bắt đầu "
                "lại từ send_self_checkin_otp để gửi mã mới."
            )
        if outcome.state == "error" and outcome.status_code == 400:
            return (
                "Hệ thống TingTing không nhận yêu cầu này (mã/phiên sai, hoặc dự án chưa hỗ trợ "
                "tự chấm công qua chat). Kiểm tra lại project_id rồi thử lại; vẫn lỗi thì nói "
                "thật là chưa thực hiện được."
            )
        return tingting_state_text(outcome)
    data = _ok_payload(outcome)
    if data is None:
        return _UNREADABLE
    verdict = render_self_checkin_verdict(data)
    await retrieval.clear_tingting_flow_state(clean_phone)
    return (
        "Đã cập nhật tự chấm công thành công. Trả lời nhân viên đúng ý sau, không thêm bớt, "
        f"không Markdown, không emoji: «{verdict}»"
    )


async def check_self_checkin_status(retrieval: GraphRetrievalPort, *, phone: str) -> str:
    """Answer "is my self check-in on?" from payroll, without mutating anything."""
    clean_phone = (phone or "").strip()
    if not clean_phone:
        return _NO_PHONE
    state = await retrieval.tingting_flow_state(clean_phone)
    action_token = str(state.get("sc_action_token") or "")
    if not action_token:
        return _NO_ACTION_TOKEN
    outcome = await retrieval.call_tingting_api(
        method="POST", path=SC_STATUS_PATH, params={"action_token": action_token}
    )
    if outcome.state == "error" and outcome.status_code == 401:
        return (
            "Phiên xác thực đã hết hiệu lực. Gọi send_self_checkin_otp để gửi mã mới, "
            "xác minh rồi kiểm tra trạng thái lại."
        )
    if outcome.state != "ok":
        return tingting_state_text(outcome)
    data = _ok_payload(outcome)
    if data is None or data.get("found") is not True:
        return _UNREADABLE
    items = _stored_assignments({"sc_assignments": data.get("assignments")})
    if not items:
        return _NO_ELIGIBLE_PROJECT
    return (
        "Trả lời nhân viên đúng ý, không thêm bớt: Tình trạng tự chấm công — "
        + "; ".join(_project_state_line(item) for item in items)
        + "."
    )


__all__ = [
    "SC_OTP_PATH",
    "SC_STATUS_PATH",
    "SC_UPDATE_PATH",
    "SC_VERIFY_PATH",
    "check_self_checkin_status",
    "confirm_self_checkin_otp",
    "render_project_menu",
    "render_self_checkin_verdict",
    "send_self_checkin_otp",
    "update_self_checkin",
]
