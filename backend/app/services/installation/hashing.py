"""Canonical hashing helpers for immutable installation evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence


def sha256_json(value: Mapping[str, object] | Sequence[object]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
