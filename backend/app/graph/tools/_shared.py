"""Private cross-domain helpers shared by the graph tool modules.

Kept out of ``__init__`` (the import-path contract surface) so tool modules can
import them without cycles; nothing outside ``app.graph.tools`` may rely on
this module.
"""

from __future__ import annotations

import json
from hashlib import sha256


def _cache_digest(*parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def _single_line(value: object, *, limit: int = 180) -> str:
    """Bound one scalar before including it in untrusted tool data."""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return f"{clipped or text[: limit - 1]}…"
