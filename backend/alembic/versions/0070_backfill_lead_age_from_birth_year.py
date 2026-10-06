"""leads.age — backfill the ages from the years candidates already gave.

The extraction prompt writes a candidate's stated year into ``birth_year``
("sinh 1976", "sn 1981") and only fills ``age`` when the candidate states an
age outright, so every candidate who gave a year without saying their age
landed with ``age IS NULL`` and a blank Tuổi column in the digest: 168 leads
on 2026-10-06, including two inside that morning's window ("Mình 1976 có
được không ạ", "minh sn 1981 có tuyển chính thức kog ạ").

One-time backfill: ``age = current Vietnam year - birth_year``, bounded by
the SAME 15..80 contract the explicit-age path and the lead-update API carry
(a year outside it is junk — the extractor drops those too). Fills NULLs only
— an explicitly-stated age is never touched.
``downgrade()`` nulls exactly the values this migration could have written
(an age still equal to the derived expression); a stated age that happens to
match the derivation is indistinguishable and costs nothing to lose.
"""

from alembic import op

revision = "0070_backfill_lead_age_from_birth_year"
down_revision = "0069_conversation_attribution"
branch_labels = None
depends_on = None

# The Vietnam year (GMT+7 — the product's own clock), not the server's UTC
# clock: a deploy at 00:xx ICT on 1 January must backfill with the year
# Vietnam is already in.
_VIETNAM_YEAR = "EXTRACT(YEAR FROM (now() AT TIME ZONE 'Asia/Ho_Chi_Minh'))::int"
_DERIVED_AGE = f"{_VIETNAM_YEAR} - birth_year"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE leads
        SET age = {_DERIVED_AGE}
        WHERE age IS NULL
          AND birth_year IS NOT NULL
          AND {_DERIVED_AGE} BETWEEN 15 AND 80
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE leads
        SET age = NULL
        WHERE birth_year IS NOT NULL AND age = {_DERIVED_AGE}
        """
    )
