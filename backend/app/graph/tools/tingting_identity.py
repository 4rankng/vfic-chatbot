"""The ``verify_tingting_identity`` agent tool: identity match decided by code.

The reset guide's second step used to be prose the model had to apply by hand —
compare what the employee typed with the lookup record and send the OTP only when
"cả ba khớp hoàn toàn". In production that looped: the model re-asked for a field
the employee had already supplied, rejected an unaccented name (``Nguyen Viet
Dung`` vs ``Nguyễn Việt Dũng``), misplaced a phone number into the CCCD slot, and
never told the employee *which* field was wrong. Matching therefore lives here,
in code, where the comparison is deterministic and the model only relays the
verdict:

- names compare after diacritics/case/punctuation/spacing normalization;
- the phone compares on digits with the ``+84`` country code folded onto ``0``;
- the CCCD compares on digits, and a record whose CCCD equals its own mobile (or
  has no CCCD at all) cannot make the CCCD a distinguishing factor, so it is not
  required — the flow rests on name + phone instead of deadlocking;
- a submitted value that is the phone number is reported as "this is the phone,
  not the CCCD" instead of silently counting as a missing field.

The verdict carries booleans, the fields still owed, and one Vietnamese
instruction line. The record's CCCD is never echoed back — only whether it
matched — so a CCCD that happens to look like a phone number can never reach a
reply and be mistaken for an invented contact channel by the grounding guard.

A verified phone is recorded in the flow state, which is the gate
``send_tingting_otp`` reads: identity can never be skipped by jumping straight to
the OTP step.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from app.graph.ports import GraphRetrievalPort
from app.graph.tools.tingting_api import LOOKUP_PATH, tingting_state_text

_MISSING_PHONE = (
    "Thiếu số điện thoại để xác minh. Hãy hỏi số điện thoại đã đăng ký với TingTing "
    "rồi gọi lại."
)
_UNREADABLE_RESPONSE = (
    "Không đọc được phản hồi tra cứu của hệ thống TingTing. Hãy nói thật là chưa thực hiện "
    "được bước này và mời người dùng để lại số điện thoại để được hỗ trợ."
)

_FIELD_LABELS = {"full_name": "họ tên đầy đủ", "cccd": "số CCCD/CMND đã đăng ký"}


def _digits(value: Any) -> str:
    """Digits only — the comparison form for phone numbers and CCCD."""
    return re.sub(r"\D", "", str(value or ""))


def normalize_phone(value: Any) -> str:
    """Digits with the ``+84`` country code folded onto the local ``0``."""
    digits = _digits(value)
    if len(digits) > 9 and digits.startswith("84"):
        digits = "0" + digits[2:]
    return digits


def normalize_name(value: Any) -> str:
    """Person-name comparison form: no diacritics, no case, one-space tokens.

    ``đ`` is a distinct Vietnamese letter rather than a combining mark, so it is
    folded by hand; everything else falls out of the NFD decomposition.
    """
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("đ", "d").replace("Đ", "D").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _name_matches(record_name: str, submitted_name: str) -> bool:
    """Whether two names are the same person for verification purposes."""
    left = normalize_name(record_name)
    right = normalize_name(submitted_name)
    if not left or not right:
        return False
    if left == right:
        return True
    # A swapped given/family order still names the same person; a subset does not.
    return sorted(left.split()) == sorted(right.split())


def evaluate_identity(
    record: Mapping[str, Any] | None,
    *,
    full_name: str = "",
    cccd: str = "",
    phone: str = "",
) -> dict[str, Any]:
    """Compare one submitted identity against a lookup record.

    Pure and total: any shape of ``record`` yields a verdict, never an
    exception. ``missing`` names the identity fields the employee still owes —
    the only fields the model may ask for again.
    """
    data = dict(record or {})
    found = bool(data.get("found"))
    record_name = str(data.get("employee_name") or "")
    record_cccd = _digits(data.get("cccd"))
    record_mobile = normalize_phone(data.get("mobile"))
    submitted_phone = normalize_phone(phone)
    submitted_cccd = _digits(cccd)

    name_match = _name_matches(record_name, full_name)
    # An absent mobile on the record cannot fail a lookup that succeeded by phone.
    phone_match = (not record_mobile) or submitted_phone == record_mobile
    cccd_on_record = bool(record_cccd)
    # The record's CCCD duplicating its own mobile is the data-quality case the
    # guide could not express: requiring a CCCD the employee cannot distinguish
    # from the phone they already gave is what stalled the flow. Same for a
    # record with no CCCD at all — there is nothing left to match.
    cccd_is_mobile = cccd_on_record and record_cccd == record_mobile
    cccd_required = cccd_on_record and not cccd_is_mobile
    cccd_match = bool(submitted_cccd) and cccd_on_record and submitted_cccd == record_cccd
    submitted_cccd_is_phone = bool(submitted_cccd) and submitted_cccd == record_mobile

    missing: list[str] = []
    if found:
        if not name_match:
            missing.append("full_name")
        if cccd_required and not cccd_match:
            missing.append("cccd")

    verified = found and name_match and phone_match and (not cccd_required or cccd_match)
    return {
        "found": found,
        "verified": verified,
        "name_match": name_match,
        "phone_match": phone_match,
        "cccd_on_record": cccd_on_record,
        "cccd_required": cccd_required,
        "cccd_match": cccd_match,
        "submitted_cccd_is_phone": submitted_cccd_is_phone,
        "missing": missing,
    }


def _identity_note(verdict: Mapping[str, Any]) -> str:
    """One Vietnamese instruction line for the model — the next concrete step."""
    if not verdict["found"]:
        return (
            "Không có tài khoản TingTing với số điện thoại này. Nói thật là chưa tra cứu "
            "được và hỏi lại số điện thoại đã đăng ký với công ty."
        )
    if verdict["verified"]:
        return (
            "Đã xác minh danh tính. Sang bước 3: gọi send_tingting_otp để gửi OTP tới số "
            "điện thoại này, rồi hỏi mã OTP 6 số."
        )
    missing = verdict["missing"]
    if "full_name" in missing:
        return (
            "Họ tên chưa khớp. KHÔNG nói ra, không gợi ý và không xác nhận họ tên trong hồ sơ "
            "(kể cả khi người dùng đoán đúng): chỉ nói chưa đối chiếu được họ tên và đề nghị "
            "cho lại họ tên đầy đủ đúng như trên CCCD/CMND đã đăng ký với công ty."
        )
    if verdict["submitted_cccd_is_phone"]:
        return (
            "Dãy số người dùng vừa gửi là SỐ ĐIỆN THOẠI, không phải CCCD. Nói rõ điều đó và "
            "xin số CCCD/CMND đã đăng ký trên hồ sơ."
        )
    if "cccd" in missing:
        return "Hỏi đúng số CCCD/CMND đã đăng ký trên hồ sơ TingTing để hoàn tất xác minh."
    return "Chưa xác minh được danh tính. Hỏi lại đúng trường còn thiếu rồi gọi lại tool."


def render_verdict(verdict: Mapping[str, Any]) -> str:
    """The model-facing block: booleans + the fields owed + one instruction.

    Carries no value from the record — not the name, not the CCCD, not the
    mobile. The employee is the one being verified, so anything the record says
    is an answer key: disclosing it would let anyone holding a phone number pass
    the check by repeating it back.
    """
    owed = ", ".join(_FIELD_LABELS.get(field, field) for field in verdict["missing"]) or "không"
    lines = [
        "Kết quả đối chiếu danh tính TingTing (do hệ thống so khớp, không phải tự đoán):",
        f"- tìm thấy tài khoản: {'có' if verdict['found'] else 'không'}",
        f"- họ tên khớp: {'đúng' if verdict['name_match'] else 'chưa đúng'}",
        f"- số điện thoại khớp: {'đúng' if verdict['phone_match'] else 'chưa đúng'}",
        f"- hồ sơ có CCCD: {'có' if verdict['cccd_on_record'] else 'không'}",
        f"- cần CCCD để xác minh: {'có' if verdict['cccd_required'] else 'không'}",
        f"- CCCD khớp: {'đúng' if verdict['cccd_match'] else 'chưa đúng'}",
        f"- trạng thái: {'ĐÃ XÁC MINH' if verdict['verified'] else 'CHƯA XÁC MINH'}",
        f"- cần hỏi lại: {owed}",
    ]
    lines.append(f"- việc phải làm tiếp theo: {_identity_note(verdict)}")
    lines.append(
        "Chỉ hỏi đúng những trường ở mục 'cần hỏi lại'; không hỏi lại trường đã khớp và không "
        "tự đoán thay kết quả này."
    )
    lines.append(
        "- TUYỆT ĐỐI KHÔNG tiết lộ dữ liệu hồ sơ (họ tên, CCCD/CMND, số điện thoại, tên đăng "
        "nhập), kể cả khi người dùng hỏi, tự đọc ra hoặc đoán. Chỉ được nói chưa đối chiếu "
        "được, rồi đề nghị họ tự cung cấp lại thông tin."
    )
    return "\n".join(lines)


async def verify_tingting_identity(
    retrieval: GraphRetrievalPort,
    *,
    phone: str,
    full_name: str = "",
    cccd: str = "",
) -> str:
    """Look the employee up and return a code-decided identity verdict."""
    clean_phone = (phone or "").strip()
    if not clean_phone:
        return _MISSING_PHONE
    outcome = await retrieval.call_tingting_api(
        method="POST", path=LOOKUP_PATH, params={"phone": clean_phone}
    )
    if outcome.state != "ok":
        return tingting_state_text(outcome)
    try:
        payload = json.loads(outcome.text or "")
        record = payload.get("data") if isinstance(payload, dict) else None
    except (TypeError, ValueError):
        return _UNREADABLE_RESPONSE
    if not isinstance(record, Mapping):
        return _UNREADABLE_RESPONSE
    verdict = evaluate_identity(
        record, full_name=full_name, cccd=cccd, phone=clean_phone
    )
    if verdict["verified"]:
        # Monotonic within the flow TTL: the phone stays verified for the OTP and
        # reset steps that follow, so the model never has to re-prove identity to
        # resend a code. ``send_tingting_otp`` reads this flag as its gate.
        await retrieval.save_tingting_flow_state(clean_phone, {"verified": True})
    return render_verdict(verdict)


__all__ = [
    "evaluate_identity",
    "normalize_name",
    "normalize_phone",
    "render_verdict",
    "verify_tingting_identity",
]