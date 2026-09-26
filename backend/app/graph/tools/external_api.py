"""The ``call_project_api`` agent tool: one truthful call into a project's API.

The admin writes the project's integration guide (``=== API NGOÀI CỦA DỰ ÁN ===``
in the prompt) and fixes the origin; the model chooses only the relative path and
the method. This module owns the Vietnamese rendering of the service's outcome.
Every expected failure is a *state*, not an exception: the model must be able to
say truthfully that it could not do the thing instead of inventing a result.
"""

from __future__ import annotations

from typing import Any

from app.graph.ports import GraphRetrievalPort

_INVALID_REQUEST = (
    "Yêu cầu không hợp lệ ({detail}). Hãy gọi lại đúng method/path như hướng dẫn "
    "API NGOÀI CỦA DỰ ÁN và chỉ truyền tham số theo mô tả."
)
_NOT_CONFIGURED = (
    "Dự án chưa cấu hình API ngoài cho việc này. Hãy nói thật và đề nghị chuyển chuyên viên hỗ trợ."
)
_RATE_LIMITED = (
    "Yêu cầu tương tự vừa được gửi trong vòng 1 phút. Hãy đề nghị người dùng chờ rồi thử lại."
)
_MISSING_PATH = (
    "Thiếu đường dẫn API. Hãy đọc hướng dẫn API NGOÀI CỦA DỰ ÁN và gọi lại kèm method và path."
)


async def call_project_api(
    retrieval: GraphRetrievalPort,
    *,
    project_slug: str | None,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> str:
    """Call one path of a project's external API.

    The returned text is bounded and truthful: the ``ok`` branch hands the real
    response body back with an explicit "answer only from this" instruction, and
    every other branch tells the model what to say instead.
    """
    requested_path = (path or "").strip()
    if not requested_path:
        return _MISSING_PATH
    outcome = await retrieval.call_project_external_api(
        project_slug=project_slug,
        method=method,
        path=requested_path,
        params=params,
    )
    if outcome.state == "ok":
        label = outcome.project_label or "dự án"
        return (
            f"Kết quả từ hệ thống ngoài ({label}):\n{outcome.text}\n"
            "Chỉ trả lời người dùng dựa trên nội dung trên; "
            "không thêm thông tin không có trong đó."
        )
    if outcome.state == "error":
        return (
            f"Hệ thống ngoài báo lỗi (HTTP {outcome.status_code}; {outcome.detail}). "
            "Hãy nói thật là chưa thực hiện được và đề nghị chuyển chuyên viên hỗ trợ."
        )
    if outcome.state == "invalid_request":
        return _INVALID_REQUEST.format(detail=outcome.detail or "sai định dạng")
    if outcome.state == "rate_limited":
        return _RATE_LIMITED
    if outcome.state == "ambiguous":
        return (
            f"Cuộc trò chuyện chưa xác định dự án ({outcome.detail}). "
            "Hãy hỏi người dùng đang làm ở dự án/nhà máy nào rồi gọi lại tool với project_slug."
        )
    # ``not_configured`` and any unexpected state: the honest answer is the same.
    return _NOT_CONFIGURED


__all__ = ["call_project_api"]
