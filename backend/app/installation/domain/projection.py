"""Safe public projection rules for the single installation manifest."""

from __future__ import annotations

import re
from collections.abc import Mapping


_SECRET_VALUE_PATTERN = re.compile(
    r"^(?:sk-|xox[a-z]*-|ghp_|github_pat_|AIza)|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",
    re.IGNORECASE,
)


def secret_like_key(key: str) -> bool:
    """Return whether a manifest key conventionally denotes credential material."""
    normalized = "".join(character for character in key.lower() if character.isalnum())
    return (
        "secret" in normalized
        or normalized.endswith("token")
        or normalized.endswith("apikey")
        or normalized.endswith("password")
        or normalized.endswith("credential")
        or normalized.endswith("privatekey")
    )


def _plain_value(value: object) -> object:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return value


def contains_secret_key(value: object) -> bool:
    """Inspect nested mappings without depending on a transport/model framework."""
    value = _plain_value(value)
    if isinstance(value, Mapping):
        return any(
            secret_like_key(str(key)) or contains_secret_key(item) for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_secret_key(item) for item in value)
    return False


def contains_secret_value(value: object) -> bool:
    """Detect recognizable credential values in arbitrarily nested manifest data."""
    value = _plain_value(value)
    if isinstance(value, Mapping):
        return any(contains_secret_value(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_secret_value(item) for item in value)
    return isinstance(value, str) and bool(_SECRET_VALUE_PATTERN.search(value.strip()))


def _safe_public_value(value: object) -> bool:
    return not contains_secret_key(value) and not contains_secret_value(value)


def project_public_mapping(
    value: Mapping[str, object], allowed_keys: frozenset[str] | set[str]
) -> dict[str, object]:
    """Allowlist public keys and fail closed on nested credential-shaped data."""
    return {
        str(key): item
        for key, item in value.items()
        if key in allowed_keys and not secret_like_key(str(key)) and _safe_public_value(item)
    }


def project_public_terminology(value: Mapping[str, object]) -> dict[str, str]:
    """Expose only safe string terminology entries from legacy or current rows."""
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, str) and not secret_like_key(str(key)) and _safe_public_value(item)
    }


__all__ = [
    "contains_secret_key",
    "contains_secret_value",
    "project_public_mapping",
    "project_public_terminology",
    "secret_like_key",
]
