"""The ``call_tingting_api`` agent tool: the TingTing app's reset API.

Deployment-wide, not project-scoped: the origin and the ``X-API-Key`` come from
the admin-managed integration settings, and the workflow guide is embedded in
:mod:`app.graph.tingting_guide`. The model chooses only the relative path, the
method and the parameters. Every expected failure is a *state*, so the model can
say truthfully that it could not do the thing instead of inventing a result.
"""

from __future__ import annotations

from typing import Any

from app.graph.ports import GraphRetrievalPort

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


async def call_tingting_api(
    retrieval: GraphRetrievalPort,
    *,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> str:
    """Call one path of the TingTing password-reset API.

    The ``ok`` branch hands the real response body back with an explicit
    "answer only from this" instruction; every other branch tells the model what
    to say instead of guessing. Secrets never appear in the rendered text.
    """
    requested_path = (path or "").strip()
    if not requested_path:
        return _MISSING_PATH
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
            "trong đó và không đọc lại mã API, session_id hay reset_token."
        )
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


__all__ = ["call_tingting_api"]
