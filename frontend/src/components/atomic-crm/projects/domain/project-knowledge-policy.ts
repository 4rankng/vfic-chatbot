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

export type ProjectDiscoveryInput = Readonly<{
  summary: string;
  location: string;
  roles: string;
  highlights: string;
}>;

export type ProjectCreationResult =
  | Readonly<{
      ok: true;
      data: Readonly<{
        knowledge_mode: ProjectKnowledgeMode;
        aliases: string[];
        discovery_card?: Readonly<{
          summary: string;
          location: string;
          roles: string[];
          eligibility: never[];
          highlights: string[];
        }>;
        is_active: false;
      }>;
    }>
  | Readonly<{
      ok: false;
      reason: "mode_required" | "discovery_required";
    }>;

export const parseCommaList = (value: string): string[] =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

export const buildProjectCreation = ({
  aliases,
  discovery,
  mode,
}: Readonly<{
  aliases: string;
  discovery: ProjectDiscoveryInput;
  mode: ProjectKnowledgeMode | "";
}>): ProjectCreationResult => {
  if (!mode) return { ok: false, reason: "mode_required" };

  if (
    mode === "DIRECT_CONTEXT" &&
    (!discovery.summary.trim() || !discovery.location.trim())
  ) {
    return { ok: false, reason: "discovery_required" };
  }

  return {
    ok: true,
    data: {
      knowledge_mode: mode,
      aliases: parseCommaList(aliases),
      discovery_card:
        mode === "DIRECT_CONTEXT"
          ? {
              summary: discovery.summary.trim(),
              location: discovery.location.trim(),
              roles: parseCommaList(discovery.roles),
              eligibility: [],
              highlights: parseCommaList(discovery.highlights),
            }
          : undefined,
      is_active: false,
    },
  };
};

export const projectReadinessLabel = (
  project: Pick<
    Project,
    "feature_readiness" | "knowledge_document_count" | "knowledge_mode"
  >,
): string => {
  if (project.knowledge_mode === "DIRECT_CONTEXT") {
    return (project.knowledge_document_count ?? 0) > 0
      ? "Đã sẵn sàng"
      : "Chưa có trang";
  }
  const ready = project.feature_readiness?.ready;
  return typeof ready === "number"
    ? `${ready}/${project.feature_readiness?.total ?? 16}`
    : "Chưa đo";
};

export const aggregateProjectFeatureReadiness = (
  projects: readonly Pick<Project, "feature_readiness" | "knowledge_mode">[],
): Readonly<{ ready: number; total: number }> =>
  projects.reduce(
    (summary, project) => {
      if (project.knowledge_mode === "DIRECT_CONTEXT") return summary;
      return {
        ready: summary.ready + (project.feature_readiness?.ready ?? 0),
        total: summary.total + (project.feature_readiness?.total ?? 0),
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
        (existing) => existing.toLocaleLowerCase() === value.toLocaleLowerCase(),
      )
    ) {
      merged.push(value);
    }
  }
  return merged;
};
