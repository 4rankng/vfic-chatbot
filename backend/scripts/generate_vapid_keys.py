#!/usr/bin/env python3
"""Print a fresh VAPID key pair as shell-ready ``KEY=value`` lines.

Used by ``scripts/prod-env.sh`` (through ``make -C backend deploy``, which runs it
on the deploy machine where this venv exists) to provision Web Push on a droplet
whose ``.env`` predates the feature. The browser subscribes with the PUBLIC key
and verifies the JWT the server signs with the PRIVATE key; both are raw base64url
(no padding), which is exactly what ``pywebpush`` and
``PushManager.subscribe({applicationServerKey})`` expect.

Rotating the pair invalidates every stored subscription, so the pair is generated
once and left alone (the caller only appends when the variable is missing).
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate_vapid_pair() -> tuple[str, str]:
    """Return ``(private_key_b64url, public_key_b64url)`` for the P-256 curve."""
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64url(private_raw), _b64url(public_raw)


def main() -> int:
    private_key, public_key = generate_vapid_pair()
    print(f"VAPID_PRIVATE_KEY={private_key}")
    print(f"VAPID_PUBLIC_KEY={public_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
