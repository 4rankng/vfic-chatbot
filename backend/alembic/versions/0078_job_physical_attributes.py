"""Job physical attributes: posture, heavy lifting, health certificate.

Zalo post-mortem 2026-10-21 (user Toàn, 19:06–19:29): the bot pitched 4P
Electronics as seated work while the plant stands its workers (the posting
itself pays a đứng-machine allowance), contradicted itself across turns, and
the user unfollowed. The fix's data half lives here: every job opening carries
structured physical attributes so a deterministic filter — not the LLM's
discretion — decides which projects may be pitched to a candidate who stated a
physical constraint.

Backfill provenance (every inferred value traces to text already stored on the
job row; anything the text does not support stays 'unknown' — the value the
hard filter treats as NOT satisfying a stated constraint):

- posture 'standing_only':
  * 4P Electronics rows — the posting pays a "trợ cấp đứng máy"/standing-
    machine allowance (post-mortem evidence), so the work is standing work.
  * any row whose title/description/requirements/benefits mention standing
    markers: "đứng máy", "đứng làm việc", "làm đứng", "trợ cấp đứng",
    "trợ cấp đứng máy", "công nhân đứng".
- posture 'seated_only': rows mentioning seated markers: "ngồi làm",
  "việc ngồi", "làm việc ngồi", "lắp ráp ngồi", "seated".
- posture 'mixed': rows whose text mentions BOTH seated and standing markers.
- heavy_lifting 'heavy_over_10kg': "mang vác nặng", "nhấc/nâng trên 10kg",
  "vận chuyển nặng". 'light_under_5kg': "mang vác nhẹ", "dưới 5kg". 'no':
  "không mang vác", "không phải mang vác", "việc nhẹ".
- health_cert 'mandatory_candidate_pays': "xét nghiệm ma túy" /
  "chứng nhận sức khỏe" / "xi-na-ban" (diacritic-folded) WITHOUT a
  company-pays marker; 'company_sponsored' when the same certificate text
  sits next to "công ty chi trả/hỗ trợ/tài trợ"; 'none_initially':
  "không cần xét nghiệm ban đầu", "chưa yêu cầu khám sức khỏe ban đầu".

All matching runs on LOWER(coalesce(...)) over ASCII/diacritic-insensitive
substrings already present in the rows (Vietnamese postings in this dataset
are written both with and without diacritics; the marker sets cover both
forms where they differ).

Revision ID: 0078_job_physical_attributes
Revises: 0077_cloudfone_transcript_days
"""

from alembic import op
import sqlalchemy as sa

revision = "0078_job_physical_attributes"
down_revision = "0077_cloudfone_transcript_days"
branch_labels = None
depends_on = None

_STANDING_MARKERS = (
    "'%dung may%'",
    "'%dung lam viec%'",
    "'%lam dung%'",
    "'%tro cap dung%'",
    "'%cong nhan dung%'",
)
_SEATED_MARKERS = (
    "'%ngoi lam%'",
    "'%viec ngoi%'",
    "'%lam viec ngoi%'",
    "'%lap rap ngoi%'",
    "'%seated%'",
)
# 4P Electronics: the standing-machine allowance is the post-mortem's own
# evidence, so the name match is an explicit override, not an inference.
_4P_NAME_MATCH = "lower(coalesce(factory_name, '') || ' ' || coalesce(title, '')) LIKE '%4p%'"

# Self-contained diacritic fold: translate() is IMMUTABLE and needs no
# unaccent extension, unlike public.unaccent (absent on some deployments).
# One call folds title/description/requirements/benefits in one pass.
_FOLD_CALL = (
    "translate(lower(coalesce(title, '') || ' ' || coalesce(description, '') || ' ' || "
    "coalesce(requirements, '') || ' ' || coalesce(benefits, '')), "
    "'áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ', "
    "'aaaaaaaaaaaaaaaaaeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuuyyyyyd')"
)


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("posture", sa.String(32), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "jobs",
        sa.Column("heavy_lifting", sa.String(32), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "jobs",
        sa.Column("health_cert", sa.String(64), nullable=False, server_default="unknown"),
    )

    text_expr = _FOLD_CALL
    standing_expr = " OR ".join(f"{text_expr} LIKE {marker}" for marker in _STANDING_MARKERS)
    seated_expr = " OR ".join(f"{text_expr} LIKE {marker}" for marker in _SEATED_MARKERS)

    op.execute(
        f"""
        UPDATE jobs SET posture = CASE
            WHEN ({_4P_NAME_MATCH}) OR ({standing_expr} AND NOT ({seated_expr}))
                THEN 'standing_only'
            WHEN ({seated_expr} AND NOT ({standing_expr})) THEN 'seated_only'
            WHEN ({standing_expr} AND ({seated_expr})) THEN 'mixed'
            ELSE 'unknown'
        END
        """
    )
    op.execute(
        f"""
        UPDATE jobs SET heavy_lifting = CASE
            WHEN {text_expr} LIKE '%mang vac nang%'
              OR {text_expr} LIKE '%nang tren 10 kg%'
              OR {text_expr} LIKE '%nang tren 10kg%'
              OR {text_expr} LIKE '%van chuyen nang%'
                THEN 'heavy_over_10kg'
            WHEN {text_expr} LIKE '%mang vac nhe%' OR {text_expr} LIKE '%duoi 5 kg%'
              OR {text_expr} LIKE '%duoi 5kg%'
                THEN 'light_under_5kg'
            WHEN {text_expr} LIKE '%khong mang vac%'
              OR {text_expr} LIKE '%khong phai mang vac%'
              OR {text_expr} LIKE '%khong yeu cau mang vac%'
                THEN 'no'
            ELSE 'unknown'
        END
        """
    )
    op.execute(
        f"""
        UPDATE jobs SET health_cert = CASE
            WHEN {text_expr} LIKE '%cong ty chi tra%'
              OR {text_expr} LIKE '%cong ty ho tro%'
              OR {text_expr} LIKE '%cong ty tai tro%'
                THEN 'company_sponsored'
            WHEN {text_expr} LIKE '%khong can xet nghiem ban dau%'
              OR {text_expr} LIKE '%chua yeu cau kham suc khoe ban dau%'
                THEN 'none_initially'
            WHEN {text_expr} LIKE '%xet nghiem ma tuy%'
              OR {text_expr} LIKE '%chung nhan suc khoe%'
              OR {text_expr} LIKE '%xi na ban%'
              OR {text_expr} LIKE '%kham suc khoe%'
                THEN 'mandatory_candidate_pays'
            ELSE 'unknown'
        END
        """
    )


def downgrade() -> None:
    op.drop_column("jobs", "health_cert")
    op.drop_column("jobs", "heavy_lifting")
    op.drop_column("jobs", "posture")
