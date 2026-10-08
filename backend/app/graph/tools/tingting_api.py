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
an optional new password.

The employee record never enters the prompt either. The lookup answers only
through :func:`verify_tingting_identity`'s booleans, and there is no agent tool
that returns the record itself: the employee is the party being verified, so a
record value in the model's context is an answer key it could be talked into
reading back.
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
    "bước này."
)
_RATE_LIMITED = (
    "Hệ thống TingTing đang giới hạn tần suất. Hãy đề nghị người dùng chờ một lát rồi thử lại."
)
_DUPLICATE_REQUEST = (
    "Yêu cầu y hệt vừa được gửi trong ít giây trước. Không gửi lại; hãy dùng kết quả của "
    "lần gọi trước đó, hoặc hỏi người dùng thêm thông tin rồi tiếp tục."
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
    "này."
)
_CODE_FORMAT = (
    "Mã xác minh phải là đúng 6 chữ số. Hãy hỏi lại mã mà nhân viên nhận được trong Zalo."
)


# The one-time password style the operator fixed: a fixed word, the symbol and
# the 6-digit code the employee just verified — ``Vfic@123980``. Readable over
# chat, typeable on a phone, and it still carries upper + lower + digit + symbol
# so the app's password policy accepts it. The app's own generator produced
# strings nobody can retype from a Zalo bubble (a real reply carried
# ``PN&&mf6P73x4``). The employee never chooses this password.
_PASSWORD_PREFIX = "Vfic"
_PASSWORD_DIGITS = 6


def generate_simple_password(otp_code: str = "") -> str:
    """The reset password: ``Vfic@<otp>``, or 6 random digits without one.

    The OTP the employee just typed is the memorable part. When the flow state
    no longer holds it (an expired session, or a flow that started before this
    format), the digits fall back to random ones so the password keeps the shape
    the operator asked for. Either way it is temporary: every reply that carries
    it tells the employee to change it after the first login.
    """
    digits = _digits(otp_code)
    if len(digits) != _PASSWORD_DIGITS:
        digits = "".join(str(secrets.randbelow(10)) for _ in range(_PASSWORD_DIGITS))
    return f"{_PASSWORD_PREFIX}@{digits}"


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
            "Hãy nói thật là chưa thực hiện được bước này."
        )
    if outcome.state == "invalid_request":
        return _INVALID_REQUEST.format(detail=outcome.detail or "sai định dạng")
    if outcome.state == "duplicate_request":
        return _DUPLICATE_REQUEST
    if outcome.state == "rate_limited":
        return _RATE_LIMITED
    # ``not_configured`` and any unexpected state: the honest answer is the same.
    return _NOT_CONFIGURED


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
    if not state.get("verified") and not await retrieval.tingting_identity_verified(clean_phone):
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
        # The code is kept server-side only, to shape the reset password
        # (``Vfic@<otp>``); it is never returned to the model or the employee.
        await retrieval.save_tingting_flow_state(
            clean_phone,
            {"reset_token": reset_token, "otp_verified": True, "otp_code": clean_code},
        )
        # The OTP landed on the registered number — 30 days of identity memory.
        await retrieval.mark_tingting_identity_verified(clean_phone)
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


async def reset_tingting_password(retrieval: GraphRetrievalPort, *, phone: str) -> str:
    """Reset the password to ``Vfic@<otp>`` with the stored token, then clear the flow.

    The employee never chooses the password: the operator fixed the format, and
    the digits are the code they just verified, so it is both memorable and read
    out of the tool result rather than invented by the model.
    """
    clean_phone = (phone or "").strip()
    if not clean_phone:
        return _NO_PHONE
    state = await retrieval.tingting_flow_state(clean_phone)
    reset_token = str(state.get("reset_token") or "")
    if not reset_token:
        return _NO_RESET_TOKEN
    generated = generate_simple_password(str(state.get("otp_code") or ""))
    params: dict[str, str] = {"reset_token": reset_token, "new_password": generated}
    outcome = await retrieval.call_tingting_api(method="POST", path=RESET_PATH, params=params)
    fell_back = False
    if outcome.state == "error" and outcome.status_code == 400:
        # The app may enforce a policy our style misses (length/composition).
        # Fall back to letting it generate one rather than failing the reset; the
        # reply then warns that the password is the app's own.
        logger.warning("tingting reset rejected the generated password; retrying without one")
        outcome = await retrieval.call_tingting_api(
            method="POST", path=RESET_PATH, params={"reset_token": reset_token}
        )
        fell_back = True
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
    # The record's ``username`` and ``employee_name`` are deliberately not read:
    # the employee logs in with the registered mobile number or CCCD, and the
    # name on file is not ours to read back to whoever holds this phone.
    password = str(data.get("new_password") or "")
    if not password:
        return _UNREADABLE
    advice = (
        "Mật khẩu này do hệ thống tự sinh nên khó nhớ ạ."
        if fell_back
        else "Mật khẩu này là mật khẩu tạm."
    )
    return (
        "Đã đặt lại mật khẩu thành công. Trả lời nhân viên đúng các ý sau, không thêm tên "
        "riêng và không đọc tên đăng nhập nội bộ:\n"
        "- tên đăng nhập: số điện thoại hoặc CCCD/CMND đã đăng ký với công ty\n"
        f"- mật khẩu mới: {password}\n"
        f"Nhắc đăng nhập ngay và đổi mật khẩu sau lần đăng nhập đầu tiên. {advice}"
    )


__all__ = [
    "LOOKUP_PATH",
    "generate_simple_password",
    "OTP_PATH",
    "RESET_PATH",
    "VERIFY_PATH",
    "confirm_tingting_otp",
    "reset_tingting_password",
    "send_tingting_otp",
    "tingting_state_text",
]