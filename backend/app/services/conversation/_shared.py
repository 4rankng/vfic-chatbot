"""Private helpers shared by the bot-send and recruiter-messaging state halves.

Single owner of the outbound delivery-status derivation from a send result:
``_delivery_status_for_send_error`` classifies an ambiguous transport failure
(the request may have reached the provider) as ``SEND_UNKNOWN``. Every state
finalizer derives its delivery status from here — do not re-derive inline.

``app/graph/runner.py`` carries a call-site mirror of the same classification
(parametrized by an injected ``send_unknown`` value). The runner side is
intentionally untouched by this package and its dedupe is tracked by the
separate runner ticket; this module is the canonical owner.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import CursorResult, Result

from app.models.conversation import DeliveryStatus
from app.shared.application.outbound import is_ambiguous_send


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# The human-visible note left when a Click-to-Messenger ad thread's reply is
# refused with Meta's closed-window error: the ad's pre-filled message is
# page-initiated, so the 24h window never opened for that PSID and the thread
# waits for the candidate's first genuine message. Lives here because both
# halves stamp it — the bot-outcome recorder (on the refused send) and the
# bot-path flag writer.
AD_ENTRY_PREFILL_SYSTEM_NOTE = (
    "Ứng viên đến từ quảng cáo Messenger và chưa tự nhắn tin nào. Meta chặn "
    "trang chủ động gửi tin trước — chờ ứng viên nhắn tin thật để tiếp tục."
)


def affected_rows(result: Result[Any]) -> int:
    """How many rows a DML statement actually touched.

    ``Session.execute`` is declared ``Result[Any]``, which carries no
    ``rowcount``, yet every caller in this package runs a conditional UPDATE
    and branches on whether it matched. The narrowing lives here so the
    conditionals stay readable and the cast is not repeated at each call.
    """
    return cast(CursorResult[Any], result).rowcount


def _delivery_status_for_send_error(error_class: str | None, *, ok: bool):
    return DeliveryStatus.SEND_UNKNOWN if is_ambiguous_send(error_class, ok=ok) else None


def merge_attribution(
    existing: dict[str, Any] | None, incoming: dict[str, Any]
) -> dict[str, Any]:
    """Fold one source touch into a conversation's first-touch record.

    First touch wins on every key it already set; a later touch only fills keys
    the record is still missing. That ordering matters for Messenger: the
    Get Started/m.me postback carries our own ``post_code`` but no Meta ids,
    while the ad's ``ad_id``/``post_id`` arrive with the first *message* — the
    second touch must be able to complete the first without replacing it.

    Blank values never count as "set" (``None`` and ``""`` are both "absent"),
    so an empty field on the first touch stays open for a later one.
    """
    if not existing:
        return dict(incoming)
    merged = dict(existing)
    for key, value in incoming.items():
        if merged.get(key) in (None, "") and value not in (None, ""):
            merged[key] = value
    return merged
