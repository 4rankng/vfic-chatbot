#!/usr/bin/env python3
"""Bootstrap the first admin/recruiter user (run once after `alembic upgrade head`).

    python -m scripts.create_admin --email admin@vfic.vn --password '...' --full-name 'Admin'

Uses the SYNC database url (psycopg). Idempotent: refuses if the email exists.
"""

import argparse
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password_sync
from app.models.user import Role, User


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the first VFIC user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--full-name", default=None)
    parser.add_argument("--role", default="admin", choices=["admin", "recruiter"])
    parser.add_argument(
        "--only-if-no-admins",
        action="store_true",
        help="Skip if ANY admin user already exists (bootstrap guard for deploy)",
    )
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.database_url_sync)
    email = args.email.strip().lower()

    with Session(engine) as session:
        # Bootstrap guard: if any admin exists, don't create another one.
        # This prevents deploy from recreating a deleted bootstrap admin
        # when a real admin account is already in use.
        if args.only_if_no_admins:
            any_admin = session.scalar(select(User.id).where(User.role == Role.admin).limit(1))
            if any_admin is not None:
                print("an admin already exists; skipping bootstrap", file=sys.stderr)
                return 0

        existing = session.scalar(select(User).where(User.email == email))
        if existing is not None:
            print(
                f"user already exists: {email} (id={existing.id}, role={existing.role.value})",
                file=sys.stderr,
            )
            return 1

        user = User(
            email=email,
            password_hash=hash_password_sync(args.password),
            full_name=args.full_name,
            role=Role(args.role),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        print(f"created {user.role.value} {email} id={user.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
