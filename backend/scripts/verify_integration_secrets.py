#!/usr/bin/env python3
"""Post-restore probe: sealed ``integration_settings`` rows must decrypt.

``integration_settings.encrypted_value`` holds ``v1:<base64(nonce+ciphertext)>``
sealed with AES-GCM under a key derived from ``INTEGRATION_SETTINGS_ENCRYPTION_KEY``
(``JWT_SECRET`` is only the legacy/dev fallback). When a restore pairs a dump
with the wrong key, every sealed row raises ``InvalidTag`` at read time and the
service skips the row with a warning — a restored stack that looks healthy while
silently discarding admin-managed credentials. This probe makes that failure
loud at restore time: it opens every sealed row with the key the current
environment provides and exits non-zero when any row fails.

Run it wherever the database and the key live together — local dev after
``make restore`` (``python -m scripts.verify_integration_secrets``) or on the
droplet via restore-droplet.sh, which pipes this file into the pinned image so
images that predate the script still get probed.

Prints row keys and counts only — never secret material. No sealed rows (or no
table at all, for pre-encryption dumps) is a pass: nothing can be lost.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.services.integration_settings import IntegrationSettingsCipher


def main() -> int:
    settings = get_settings()
    cipher = IntegrationSettingsCipher(settings)
    engine = create_engine(settings.database_url_sync)
    with engine.begin() as conn:
        if (
            conn.execute(
                text("SELECT to_regclass('public.integration_settings')")
            ).scalar()
            is None
        ):
            print(
                "verify_integration_secrets: no integration_settings table "
                "(pre-encryption dump) — nothing to verify"
            )
            return 0
        rows = conn.execute(
            text(
                "SELECT key, encrypted_value FROM integration_settings "
                "WHERE is_secret AND encrypted_value LIKE 'v1:%'"
            )
        ).fetchall()

    undecryptable: list[str] = []
    for key, stored in rows:
        try:
            cipher.decrypt(stored)
        except Exception:  # noqa: BLE001 — any failure to open means the row is lost
            undecryptable.append(key)

    if undecryptable:
        print(
            f"verify_integration_secrets: {len(undecryptable)} of {len(rows)} "
            "sealed rows do NOT decrypt with the current key (InvalidTag)."
        )
        print("  affected keys: " + ", ".join(sorted(undecryptable)))
        print(
            "  the data was sealed under a different key — restore the .env the "
            "backup captured (make backup / backup-full ship it) and re-run."
        )
        return 1
    print(
        f"verify_integration_secrets: all {len(rows)} sealed row(s) decrypt cleanly."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
