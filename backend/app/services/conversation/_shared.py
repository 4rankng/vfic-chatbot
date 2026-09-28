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
