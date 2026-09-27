"""The TingTing reset tools: one egress site, server-side flow state.

The reset workflow spans turns (lookup → verify identity → OTP → code → reset),
but an agent turn's message list does not: tool results from the previous turn
are gone, so a ``session_id`` the model was handed with the OTP is unavailable
when the employee replies with the code. Production showed the consequence — the
code turn called ``password-reset/verify`` with a stale/absent session and got
HTTP 400, and every "resend the OTP" minted a new session while the model held
the old one, so the employee was told the code was expired although it had just
arrived.

The steps therefore live in code, keyed by the employee's phone digits:

- :func:`verify_tingting_identity` decides the identity match and records that the
  phone passed verification;
- :func:`send_tingting_otp` sends the OTP and stores the session it created;
- :func:`confirm_tingting_otp` verifies the code against that stored session;
- :func:`reset_tingting_password` resets with the stored reset token.

``session_id`` and ``reset_token`` never enter the prompt, and the model cannot
supply them: the only param it owns is the employee's phone, the 6-digit code and
an optional new password. :func:`call_tingting_api` stays available for the
read-only lookup but refuses every mutating path with a pointer at these tools.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from typing import Any

from app.graph.ports import GraphRetrievalPort

logger = logging.getLogger(__name__)

# The reset API's read path, named once: the guide, the tool schema and the
# identity verifier all quote the same path.
LOOKUP_PATH = "/api/v1/integration/employee/lookup"
OTP_PATH = "/api/v1/integration/password-reset/otp"
VERIFY_PATH = "/api/v1/integration/password-reset/verify"
RESET_PATH = "/api/v1/integration/password-reset/reset"

_INVALID_REQUEST = (
    "Yêu cầu không hợp lệ ({detail}). Hãy gọi lại đúng method/path như hướng dẫn "
    "API TINGTING và chỉ truyền tham số theo mô tả."
)
_NOT_CONFIGURED = (
    "Hệ thống TingTing chưa được cấu hình khóa API. Hãy nói thật là chưa thực hiện được "
    "và mời người dùng để lại số điện thoại để được hỗ trợ."
)
_RATE_LIMITED = (
    "Hệ thống TingTing đang giới hạn tần suất. Hãy đề nghị người dùng chờ một lát rồi thử lại."
)
_DUPLICATE_REQUEST = (
    "Yêu cầu y hệt vừa được gửi trong ít giây trước. Không gửi lại; hãy dùng kết quả của "
    "lần gọi trước đó, hoặc hỏi người dùng thêm thông tin rồi tiếp tục."
)
_MISSING_PATH = (
    "Thiếu đường dẫn API. Hãy đọc hướng dẫn API TINGTING và gọi lại kèm method và path."
)
_MUTATING_PATH_REFUSED = (
    "Không gọi trực tiếp endpoint này: các bước gửi OTP / xác thực mã / đặt lại mật khẩu phải "
    "dùng send_tingting_otp, confirm_tingting_otp và reset_tingting_password để hệ thống giữ "
    "phiên xác minh. call_tingting_api chỉ dùng để tra cứu nhân viên."
)
_NO_PHONE = (
    "Thiếu số điện thoại. Hãy hỏi số điện thoại đã đăng ký với công ty rồi gọi lại tool."
)
_NOT_VERIFIED = (
    "Số điện thoại này chưa được xác minh danh tính. Hãy gọi verify_tingting_identity với họ "
    "tên/CCCD mà nhân viên đã cung cấp và chỉ gửi OTP khi tool trả về ĐÃ XÁC MINH."
)
_NO_OTP_SESSION = (
    "Chưa có phiên OTP còn hiệu lực cho số điện thoại này. Hãy gọi send_tingting_otp để gửi "
    "mã mới, rồi xin mã 6 số mà nhân viên nhận được."
)
_NO_RESET_TOKEN = (
    "Chưa xác thực được mã OTP cho số điện thoại này nên chưa thể đặt lại mật khẩu. Hãy gọi "
    "send_tingting_otp rồi confirm_tingting_otp trước."
)
_UNREADABLE = (
    "Không đọc được phản hồi của hệ thống TingTing. Hãy nói thật là chưa thực hiện được bước "
    "này và mời người dùng để lại số điện thoại để được hỗ trợ."
)
_CODE_FORMAT = (
    "Mã xác minh phải là đúng 6 chữ số. Hãy hỏi lại mã mà nhân viên nhận được trong Zalo."
)


# One-time password style the operator asked for: readable over chat and easy to
# type on a phone, while still carrying upper + lower + digit + symbol so the
# app's password policy accepts it. The system-generated one (a real report:
# ``PN&&mf6P73x4``) was unreadable when an employee had to key it in.
_PASSWORD_WORDS: tuple[str, ...] = (
    "Matkhau",
    "Tingting",
    "Dangnhap",
    "Congviec",
    "Thanhcong",
)
_PASSWORD_SYMBOLS: tuple[str, ...] = ("@", "#", "$")
_PASSWORD_DIGITS = 6


def generate_simple_password() -> str:
    """A memorable one-time password: ``Matkhau@482913``.

    10^6 digit combinations behind a known word: weaker than a random 12-char
    string, which is the operator's explicit trade for a credential the employee
    can actually type. It is one-time anyway — every reply that carries it also
    tells the employee to change it after the first login.
    """
    word = secrets.choice(_PASSWORD_WORDS)
    symbol = secrets.choice(_PASSWORD_SYMBOLS)
    digits = "".join(str(secrets.randbelow(10)) for _ in range(_PASSWORD_DIGITS))
    return f"{word}{symbol}{digits}"


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _ok_payload(outcome: Any) -> dict[str, Any] | None:
    """The ``data`` object of an ``ok`` response, or ``None`` when unreadable."""
    if getattr(outcome, "state", None) != "ok":
        return None
    try:
        payload = json.loads(getattr(outcome, "text", "") or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def tingting_state_text(outcome: Any) -> str:
    """The model-facing text for a non-``ok`` TingTing outcome.

    Shared by every TingTing tool so a failure reads the same wherever it is
    surfaced: each state says what to tell the employee instead of inviting a
    guess at what happened.
    """
    if outcome.state == "error":
        return (
            f"Hệ thống TingTing báo lỗi (HTTP {outcome.status_code}; {outcome.detail}). "
            "Hãy nói thật là chưa thực hiện được và mời người dùng để lại số điện thoại để "
            "được hỗ trợ."
        )
    if outcome.state == "invalid_request":
        return _INVALID_REQUEST.format(detail=outcome.detail or "sai định dạng")
    if outcome.state == "duplicate_request":
        return _DUPLICATE_REQUEST
    if outcome.state == "rate_limited":
        return _RATE_LIMITED
    # ``not_configured`` and any unexpected state: the honest answer is the same.
    return _NOT_CONFIGURED


async def call_tingting_api(
    retrieval: GraphRetrievalPort,
    *,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> str:
    """Read the employee record. Mutating paths are refused here.

    Only the lookup is reachable through this tool: the reset steps carry flow
    state that must not depend on the model, so they have their own tools.
    """
    requested_path = (path or "").strip()
    if not requested_path:
        return _MISSING_PATH
    if requested_path not in {LOOKUP_PATH}:
        return _MUTATING_PATH_REFUSED
    outcome = await retrieval.call_tingting_api(
        method=method,
        path=requested_path,
        params=params,
    )
    if outcome.state == "ok":
        return (
            "Kết quả từ hệ thống TingTing:\n"
            f"{outcome.text}\n"
            "Chỉ trả lời người dùng dựa trên nội dung trên; không thêm thông tin không có "
            "trong đó và không đọc lại mã API hay mã định danh nội bộ."
        )
    return tingting_state_text(outcome)


def _otp_failure_text(data: dict[str, Any]) -> str:
    """Map the OTP endpoint's ``failure_reason`` onto the next step."""
    reason = str(data.get("failure_reason") or "")
    if reason == "account_not_found":
        return (
            "Không có duy nhất một tài khoản với số điện thoại này. Hỏi lại số điện thoại đã "
            "đăng ký với công ty."
        )
    if reason == "zalo_disabled":
        return "Kênh OTP qua Zalo đang tắt. Nói thật là chưa gửi được và đề nghị thử lại sau."
    if reason == "delivery_failed":
        if int(data.get("delivery_error_code") or 0) == -118:
            return (
                "Zalo không gửi được vì số này chưa liên kết Zalo. Đề nghị nhân viên mở/liên "
                "kết Zalo bằng số đã đăng ký rồi nhắn lại để gửi lại mã."
            )
        return "Zalo không gửi được mã. Đề nghị thử lại sau."
    return "Chưa gửi được mã xác minh. Nói thật là chưa thực hiện được bước này."


async def send_tingting_otp(retrieval: GraphRetrievalPort, *, phone: str) -> str:
    """Send the OTP for a verified phone and store the session it created."""
    clean_phone = (phone or "").strip()
    if not clean_phone:
        return _NO_PHONE
    state = await retrieval.tingting_flow_state(clean_phone)
    if not state.get("verified"):
        return _NOT_VERIFIED
    outcome = await retrieval.call_tingting_api(
        method="POST", path=OTP_PATH, params={"phone": clean_phone}
    )
    if outcome.state == "duplicate_request":
        return (
            "Mã xác minh vừa được gửi cho số này trong ít giây trước. Nói nhân viên kiểm tra Zalo "
            "và gửi mã 6 số vừa nhận; nếu chưa nhận được thì chờ khoảng 1 phút rồi gọi lại tool này."
        )
    if outcome.state != "ok":
        return tingting_state_text(outcome)
    data = _ok_payload(outcome)
    if data is None:
        return _UNREADABLE
    session_id = str(data.get("session_id") or "")
    if data.get("otp_sent") is not True or not session_id:
        return _otp_failure_text(data)
    await retrieval.save_tingting_flow_state(clean_phone, {"session_id": session_id})
    return (
        "Đã gửi mã xác minh 6 số qua Zalo tới số điện thoại này. Hãy hỏi nhân viên mã 6 số vừa "
        "nhận, rồi gọi confirm_tingting_otp(phone, code). Không hỏi lại số điện thoại và không "
        "đọc mã định danh phiên cho người dùng."
    )


async def confirm_tingting_otp(
    retrieval: GraphRetrievalPort, *, phone: str, code: str
) -> str:
    """Verify the employee's 6-digit code against the stored OTP session."""
    clean_phone = (phone or "").strip()
    if not clean_phone:
        return _NO_PHONE
    state = await retrieval.tingting_flow_state(clean_phone)
    session_id = str(state.get("session_id") or "")
    if not session_id:
        return _NO_OTP_SESSION
    clean_code = _digits(code)
    if len(clean_code) != 6:
        return _CODE_FORMAT
    outcome = await retrieval.call_tingting_api(
        method="POST", path=VERIFY_PATH, params={"session_id": session_id, "code": clean_code}
    )
    if outcome.state == "ok":
        data = _ok_payload(outcome)
        reset_token = str((data or {}).get("reset_token") or "")
        if not reset_token:
            return _UNREADABLE
        await retrieval.save_tingting_flow_state(
            clean_phone, {"reset_token": reset_token, "otp_verified": True}
        )
        return (
            "Mã đúng. Hãy gọi reset_tingting_password(phone) để đặt lại mật khẩu cho nhân viên; "
            "không xin thêm thông tin nào nữa."
        )
    if outcome.state == "duplicate_request":
        return (
            "Mã này vừa được kiểm tra trong ít giây trước. Hãy hỏi lại mã nhân viên nhận được; nếu "
            "vẫn là mã cũ thì chờ khoảng 1 phút rồi thử lại, hoặc gọi send_tingting_otp để gửi mã mới."
        )
    if outcome.state == "error" and outcome.status_code == 401:
        # A wrong or expired code keeps the session: the same session accepts a
        # retry, and a fresh code needs a fresh send.
        return (
            "Mã 6 số không đúng hoặc đã hết hạn (phiên vẫn còn trong ít phút). Hỏi lại mã trong "
            "Zalo; nếu nhân viên không nhận được mã mới thì gọi send_tingting_otp để gửi lại."
        )
    if outcome.state == "error" and outcome.status_code == 400:
        return "Mã hoặc phiên không hợp lệ. Hỏi lại đúng mã 6 số mà nhân viên nhận được."
    return tingting_state_text(outcome)


async def reset_tingting_password(
    retrieval: GraphRetrievalPort, *, phone: str, new_password: str = ""
) -> str:
    """Reset the password with the stored reset token and clear the flow."""
    clean_phone = (phone or "").strip()
    if not clean_phone:
        return _NO_PHONE
    state = await retrieval.tingting_flow_state(clean_phone)
    reset_token = str(state.get("reset_token") or "")
    if not reset_token:
        return _NO_RESET_TOKEN
    requested = (new_password or "").strip()
    # No explicit password from the employee: set our own memorable one instead
    # of letting the app mint an unreadable string.
    generated = "" if requested else generate_simple_password()
    params: dict[str, str] = {"reset_token": reset_token, "new_password": requested or generated}
    outcome = await retrieval.call_tingting_api(method="POST", path=RESET_PATH, params=params)
    if (
        generated
        and outcome.state == "error"
        and outcome.status_code == 400
    ):
        # The app may enforce a policy our style misses (length/composition).
        # Fall back to letting it generate one rather than failing the reset; the
        # reply then warns that the password is the app's own.
        logger.warning("tingting reset rejected the simple password; retrying without one")
        outcome = await retrieval.call_tingting_api(
            method="POST", path=RESET_PATH, params={"reset_token": reset_token}
        )
        generated = ""
    if outcome.state != "ok":
        if outcome.state == "error" and outcome.status_code == 401:
            await retrieval.clear_tingting_flow_state(clean_phone)
            return (
                "Phiên xác thực đã hết hiệu lực nên chưa đặt lại được mật khẩu. Hãy bắt đầu lại "
                "từ send_tingting_otp để gửi mã mới."
            )
        return tingting_state_text(outcome)
    data = _ok_payload(outcome)
    if data is None:
        return _UNREADABLE
    await retrieval.clear_tingting_flow_state(clean_phone)
    username = str(data.get("username") or "")
    password = str(data.get("new_password") or "")
    employee = str(data.get("employee_name") or "")
    if not username or not password:
        return _UNREADABLE
    label = f" cho {employee}" if employee else ""
    advice = (
        "Mật khẩu này do hệ thống tự sinh nên khó nhớ ạ."
        if not generated
        else "Mật khẩu này là mật khẩu tạm, anh/chị đổi lại ngay sau khi đăng nhập ạ."
    )
    return (
        f"Đã đặt lại mật khẩu{label} thành công. Đọc lại cho nhân viên đúng tên đăng nhập và "
        f"mật khẩu mới sau đây, đúng từng ký tự, rồi nhắc đổi mật khẩu sau lần đăng nhập đầu "
        f"tiên. {advice}\n"
        f"- tên đăng nhập: {username}\n- mật khẩu mới: {password}"
    )


__all__ = [
    "LOOKUP_PATH",
    "generate_simple_password",
    "OTP_PATH",
    "RESET_PATH",
    "VERIFY_PATH",
    "call_tingting_api",
    "confirm_tingting_otp",
    "reset_tingting_password",
    "send_tingting_otp",
    "tingting_state_text",
]