"""Worker product-feature catalog + per-project feature values.

A "project" doubles as a product the agent sells (see migration 0003). This adds the
structured layer that turns an uploaded job posting into agent knowledge the chatbot can
answer from like a recruitment consultant:

  * ``worker_feature_catalog`` — the 16 worker-interest product features (income, pay
    frequency, overtime, schedule, commute, housing, application simplicity, joining
    bonus, daily-cost benefits, health & safety, job difficulty, trust, work-life,
    contract security, career growth). Seeded here as idempotent data.
  * ``job_feature_values`` — one row per (project, feature) holding the LLM-extracted
    ``value_text`` + structured ``value_json`` (min/max/currency/period/breakdown…),
    highlight/missing/needs-clarification flags, evidence quote, and the source document.
    UNIQUE(project_id, feature_id) so re-extraction upserts cleanly.

The feature-extraction step runs inside ``KnowledgePipeline`` (after embed/index), so no
graph change is required to populate these; the agent reaches them via the new
``get_product_features`` tool. Embeddings are untouched (still vector(3072) Gemini).

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-27
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.worker_feature_catalog (
          id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          feature_key              text NOT NULL,
          name_vi                  text NOT NULL,
          category                 text NOT NULL,
          worker_question_vi       text,
          description              text,
          default_importance_score numeric(5,2) NOT NULL DEFAULT 0.50,
          created_at               timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX worker_feature_catalog_feature_key_key
          ON public.worker_feature_catalog (feature_key);
        """
    )

    op.execute(
        """
        CREATE TABLE public.job_feature_values (
          id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id           uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
          feature_id           uuid NOT NULL REFERENCES public.worker_feature_catalog(id) ON DELETE CASCADE,
          value_text           text NOT NULL,
          value_json           jsonb NOT NULL DEFAULT '{}'::jsonb,
          strength_score       numeric(5,2) NOT NULL DEFAULT 0.50,
          display_priority     integer NOT NULL DEFAULT 100,
          is_highlight         boolean NOT NULL DEFAULT false,
          is_missing           boolean NOT NULL DEFAULT false,
          needs_clarification  boolean NOT NULL DEFAULT false,
          evidence_text        text,
          source_document_id   uuid REFERENCES public.knowledge_documents(id) ON DELETE SET NULL,
          created_at           timestamptz NOT NULL DEFAULT now(),
          updated_at           timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT job_feature_values_project_feature_key UNIQUE (project_id, feature_id)
        );
        CREATE INDEX job_feature_values_project_idx ON public.job_feature_values (project_id);
        CREATE TRIGGER job_feature_values_touch
          BEFORE UPDATE ON public.job_feature_values
          FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
        """
    )

    # Seed the 16 worker-interest product features (idempotent — safe on re-apply).
    op.execute(
        """
        INSERT INTO public.worker_feature_catalog
          (feature_key, name_vi, category, worker_question_vi, default_importance_score) VALUES
          ('take_home_income',     'Thu nhập thực nhận',          'income',          'Một tháng tôi nhận được khoảng bao nhiêu tiền?',         1.00),
          ('pay_frequency',        'Kỳ lương (lương tuần)',       'cashflow',        'Khi nào tôi được nhận tiền?',                             0.95),
          ('salary_transparency',  'Chi tiết lương và phụ cấp',   'income',          'Lương gồm những khoản nào, có rõ ràng không?',           0.90),
          ('shift_schedule',       'Lịch ca làm việc',            'schedule',        'Tôi làm ca nào, nghỉ ngày nào?',                         0.90),
          ('trust_signal',         'Độ tin cậy của tin tuyển dụng','trust',          'Tin này có thật không, có mất phí không?',               0.90),
          ('overtime_rate',        'Tỷ lệ tăng ca',               'income',          'Tăng ca tính tiền thế nào?',                             0.85),
          ('housing',              'Ký túc xá / nhà ở',           'housing',         'Ở xa có chỗ ở không, điều kiện thế nào?',                0.85),
          ('job_difficulty',       'Nội dung công việc',          'job_difficulty',  'Tôi sẽ làm việc gì mỗi ngày, có vất vả không?',         0.85),
          ('commute_support',      'Xe đưa đón',                  'commute',         'Từ chỗ tôi có xe đi làm không?',                         0.95),
          ('application_simplicity','Hồ sơ đăng ký đơn giản',      'application',     'Tôi cần giấy tờ gì để đi làm?',                          0.80),
          ('joining_bonus',        'Thưởng đi làm',               'bonus',           'Có thưởng thêm khi mới đi làm không?',                   0.80),
          ('contract_security',    'Hợp đồng và bảo hiểm',         'legal_security',  'Tôi có hợp đồng, bảo hiểm không?',                       0.80),
          ('daily_cost_benefits',  'Phúc lợi giảm chi phí',       'daily_cost',      'Công ty hỗ trợ chi phí ăn ở, đi lại gì?',                0.75),
          ('health_safety',        'Sức khỏe và an toàn',          'health_safety',   'Công việc có an toàn không, ảnh hưởng sức khỏe không?',  0.75),
          ('work_life_balance',    'Môi trường và cân bằng',       'work_life',       'Môi trường làm việc có thoải mái không?',                0.70),
          ('career_growth',        'Cơ hội phát triển',            'career_growth',   'Có cơ hội lên chức, tăng lương không?',                  0.65)
        ON CONFLICT (feature_key) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS job_feature_values_touch ON public.job_feature_values; "
        "DROP TABLE IF EXISTS public.job_feature_values CASCADE;"
    )
    op.execute("DROP TABLE IF EXISTS public.worker_feature_catalog CASCADE;")
