"""The VAPID pair the deploy provisions must be usable by both ends.

``scripts/generate_vapid_keys.py`` prints what ``prod-env.sh`` appends to the
droplet's ``.env``: the server signs push JWTs with the private half and the
browser subscribes with the public half, so the shapes are a contract, not an
implementation detail — a private scalar that is not 32 bytes, or a public point
that is not the 65-byte uncompressed form, silently breaks every subscription.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric import ec

from scripts.generate_vapid_keys import generate_vapid_pair


def _decode(value: str) -> bytes:
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(padded)


def test_generates_a_usable_p256_pair():
    private_key, public_key = generate_vapid_pair()

    private_raw = _decode(private_key)
    public_raw = _decode(public_key)

    assert len(private_raw) == 32
    assert public_raw[0] == 0x04  # uncompressed point, what PushManager expects
    assert len(public_raw) == 65
    # "-" and "_" only: base64url without padding is what both ends parse.
    assert set(private_key) | set(public_key) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )


def test_each_call_generates_a_distinct_pair():
    first = generate_vapid_pair()
    second = generate_vapid_pair()

    assert first != second


def test_public_key_is_the_pair_of_the_printed_private_key():
    """The two halves must match, or nothing the server signs verifies."""
    private_key, public_key = generate_vapid_pair()

    derived = ec.derive_private_key(
        int.from_bytes(_decode(private_key), "big"), ec.SECP256R1()
    ).public_key()

    assert (
        derived.public_numbers().x.to_bytes(32, "big") + derived.public_numbers().y.to_bytes(32, "big")
        == _decode(public_key)[1:]
    )
