import type { ProductFeature, Project } from "../../types";

export const PROJECT_KNOWLEDGE_CATEGORIES = [
  "jobs",
  "compensation",
  "requirements",
  "work_schedules",
  "benefits",
  "accommodation",
  "meals",
  "transportation",
  "insurance",
  "application",
  "contacts",
  "faq",
] as const;

export type ProjectKnowledgeCategory =
  (typeof PROJECT_KNOWLEDGE_CATEGORIES)[number];
export type ProjectKnowledgeMode = "RAG" | "DIRECT_CONTEXT";

/** The ONE Vietnamese label per knowledge category. Every surface that names a
 *  category (the external-source picker, the brief import summary) reads this
 *  table — a second local list is how the two drift apart. */
export const PROJECT_KNOWLEDGE_CATEGORY_LABELS: Readonly<
  Record<ProjectKnowledgeCategory, string>
> = {
  faq: "Câu hỏi thường gặp",
  jobs: "Vị trí tuyển dụng",
  compensation: "Lương & thu nhập",
  requirements: "Yêu cầu ứng viên",
  work_schedules: "Ca làm việc",
  benefits: "Phúc lợi",
  accommodation: "Chỗ ở",
  meals: "Bữa ăn",
  transportation: "Đưa đón & lịch xe",
  insurance: "Bảo hiểm",
  application: "Ứng tuyển & nhận việc",
  contacts: "Liên hệ",
};

export type ProjectDiscoveryInput = Readonly<{
  summary: string;
  location: string;
  roles: string;
  highlights: string;
}>;

export type ProjectCreationPayload = Readonly<{
  knowledge_mode: ProjectKnowledgeMode;
  aliases: string[];
  is_active: false;
}>;

export const parseCommaList = (value: string): string[] =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

/**
 * The payload `Tạo dự án` creates the DRAFT with.
 *
 * Three deliberate constants, each one a backend rule rather than a preference:
 *
 * - `knowledge_mode` is always RAG. The mode used to be a recruiter choice, but
 *   this form is driven by the category ingest pipeline, and that pipeline only
 *   exists on the RAG path — a single-page project has no categories to write.
 * - `is_active` is always false. The create schema refuses an active project
 *   outright ("A new Project can be activated after its knowledge is ready"),
 *   so activation is the final button, never a side effect of uploading.
 * - `discovery_card` is NEVER sent. The create schema rejects one on a RAG
 *   project outright — "RAG discovery cards are derived from active categories"
 *   — so the summary, location, roles and highlights the brief carries reach
 *   the assistant through the category YAML that is ingested, not through a
 *   field on the project row. Collecting them as editable inputs here would
 *   promise the recruiter an edit that the API discards.
 */
export const buildProjectCreation = ({
  aliases,
}: Readonly<{
  aliases: string;
}>): ProjectCreationPayload => ({
  knowledge_mode: "RAG",
  aliases: parseCommaList(aliases),
  is_active: false,
});

/** A nullable mode identifies a legacy project without its own knowledge base. */
export const projectKnowledgeModeLabel = (
  mode: Project["knowledge_mode"],
): string => {
  if (mode === "DIRECT_CONTEXT") return "Một trang";
  if (mode === "RAG") return "Theo danh mục";
  return "Kiến thức cũ";
};

export const projectReadinessLabel = (
  project: Pick<
    Project,
    "category_readiness" | "knowledge_document_count" | "knowledge_mode"
  >,
): string => {
  if (project.knowledge_mode === "DIRECT_CONTEXT") {
    return (project.knowledge_document_count ?? 0) > 0
      ? "Đã sẵn sàng"
      : "Chưa có trang";
  }
  const ready = project.category_readiness?.ready;
  const total = project.category_readiness?.total;
  return typeof ready === "number" && typeof total === "number" && total > 0
    ? `${ready}/${total}`
    : "Chưa đo";
};

export const aggregateProjectCategoryReadiness = (
  projects: readonly Pick<Project, "category_readiness" | "knowledge_mode">[],
): Readonly<{ ready: number; total: number }> =>
  projects.reduce(
    (summary, project) => {
      if (project.knowledge_mode === "DIRECT_CONTEXT") return summary;
      return {
        ready: summary.ready + (project.category_readiness?.ready ?? 0),
        total: summary.total + (project.category_readiness?.total ?? 0),
      };
    },
    { ready: 0, total: 0 },
  );

export const isProductFeatureReady = (
  feature: ProductFeature | null | undefined,
): boolean =>
  Boolean(
    feature?.value_text?.trim() &&
      !feature.is_missing &&
      !feature.needs_clarification,
  );

export const orderProductFeatureSlots = (
  features: readonly ProductFeature[] | null,
  totalSlots: number,
): (ProductFeature | null)[] => {
  const sorted = [...(features ?? [])].sort(
    (left, right) => left.display_priority - right.display_priority,
  );
  return Array.from(
    { length: Math.max(0, totalSlots) },
    (_, index) => sorted[index] ?? null,
  );
};

/**
 * The backend's frozen activation-conflict messages, in the console's
 * Vietnamese. The texts are an API contract (pinned by backend domain tests),
 * so this maps rather than re-translates at every call site; anything unknown
 * falls through untouched.
 */
const ACTIVATION_CONFLICTS_VI: Readonly<Record<string, string>> = {
  "RAG Project needs an active Jobs category before activation":
    "Dự án cần danh mục Tuyển dụng (Jobs) có dữ liệu trước khi bật. Hãy nạp danh mục trước.",
  "Single-page Project needs a discovery card before activation":
    "Dự án Một trang cần thẻ khám phá trước khi bật.",
  "Single-page Project needs its page before activation":
    "Dự án Một trang cần trang kiến thức trước khi bật.",
  "Project has no owned knowledge base": "Dự án chưa có kiến thức nền để bật.",
};

export const projectActivationConflictVi = (message: string): string =>
  ACTIVATION_CONFLICTS_VI[message] ?? message;

export type NormalizedProjectFaq = Readonly<{
  question: string;
  answer: string;
  question_variants: string[];
  required_terms: string[];
  forbidden_terms: string[];
}>;

export const normalizeProjectFaq = (
  value: NormalizedProjectFaq,
): NormalizedProjectFaq | null => {
  const question = value.question.trim();
  const answer = value.answer.trim();
  return question && answer ? { ...value, question, answer } : null;
};

export const mergeUniqueTerms = (
  current: readonly string[],
  input: string,
): string[] => {
  const merged = [...current];
  for (const value of parseCommaList(input)) {
    if (
      !merged.some(
        (existing) =>
          existing.toLocaleLowerCase() === value.toLocaleLowerCase(),
      )
    ) {
      merged.push(value);
    }
  }
  return merged;
};
