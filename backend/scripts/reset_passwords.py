#!/usr/bin/env python3
"""Reset every user's password (dev-only; run after restoring a DB backup).

    python -m scripts.reset_passwords --password admin123

Rewrites all ``users.password_hash`` values and bumps ``token_version`` so any
previously issued JWT is invalidated. Uses the SYNC database url (psycopg),
mirroring ``scripts.create_admin``.
"""

import argparse

from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.security import hash_password_sync


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset all user passwords.")
    parser.add_argument("--password", default="admin123")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.database_url_sync)
    new_hash = hash_password_sync(args.password)

    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE users "
                "SET password_hash = :h, token_version = token_version + 1"
            ),
            {"h": new_hash},
        )
    print(f"reset {result.rowcount} user(s) to password: {args.password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
