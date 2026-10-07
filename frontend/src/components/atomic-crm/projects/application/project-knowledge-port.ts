import type {
  BusTimetableList,
  ProductFeature,
  ProductFeatureList,
  Project,
} from "../../types";
import type {
  CategoryAuthorityState,
  FeaturePatch,
  KnowledgeCategoryCatalog,
  KnowledgeCategoryRevision,
  KnowledgeCategorySource,
  KnowledgeCategoryTemplate,
  ProjectFaq,
  ProjectFaqList,
  ProjectFaqPayload,
  ProjectKnowledgeExport,
  SinglePageKnowledge,
} from "../domain/project-knowledge-contracts";
import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";

export type CancellationSignal = Readonly<{
  aborted: boolean;
  onAbort: (listener: () => void) => () => void;
}>;

/** A source file uploaded as a project knowledge document (multipart). */
export type ProjectDocumentUpload = Readonly<{
  name: string;
  type: string;
  bytes: ArrayBuffer;
}>;

export type ProjectTrainingWrite = Readonly<{
  key: ProjectKnowledgeCategory;
  filename: string;
  content: string;
}>;

export type ProjectTrainingDocument = Readonly<{
  id: string;
  status: "UPLOADED" | "PROCESSING" | "PUBLISHED" | "FAILED" | "ARCHIVED";
  stage: string;
  error: string | null;
  project_training: Readonly<{
    status: "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED";
    current: ProjectKnowledgeCategory | null;
    completed: readonly ProjectKnowledgeCategory[];
    /** Categories extracted from this source by the backend worker. */
    planned?: readonly ProjectKnowledgeCategory[];
    /** Checkpointed brief-extraction counts; stale once categories train. */
    source_sections_total?: number;
    source_sections_completed?: number;
    error: string | null;
    /** Reviewed shadow categories still await an explicit authority cutover. */
    requires_cutover?: boolean;
  }> | null;
}>;

/**
 * A partial write to the recruiter-authored half of a project record: the
 * discovery card the agent matches candidates against, plus the aliases used to
 * recognise the project in a conversation. The backend merges the card into the
 * project's `index_card` — only the keys present here are written — so a caller
 * sends exactly the keys it owns: the discovery-card draft sends the whole
 * card, while the brief chain carries `highlights` alone.
 */
export type ProjectDiscoveryCardPatch = Readonly<{
  aliases?: string[];
  discovery_card: Readonly<
    Partial<{
      summary: string;
      location: string;
      roles: string[];
      eligibility: never[];
      highlights: string[];
    }>
  >;
}>;

export type ProjectKnowledgePort = Readonly<{
  getCategories: (projectId: string) => Promise<KnowledgeCategoryCatalog>;
  getCategoryTemplate: (
    projectId: string,
    key: ProjectKnowledgeCategory,
  ) => Promise<KnowledgeCategoryTemplate>;
  getFullTemplate: (
    projectId: string,
    signal?: CancellationSignal,
  ) => Promise<ProjectKnowledgeExport>;
  getKnowledgeExport: (
    projectId: string,
    signal?: CancellationSignal,
  ) => Promise<ProjectKnowledgeExport>;
  getCategorySource: (
    projectId: string,
    key: ProjectKnowledgeCategory,
  ) => Promise<KnowledgeCategorySource>;
  replaceCategory: (
    projectId: string,
    key: ProjectKnowledgeCategory,
    filename: string,
    content: string,
  ) => Promise<{ revision: KnowledgeCategoryRevision; job_id: string }>;
  /** Replace a category's active content with an explicit empty state. */
  clearCategory: (
    projectId: string,
    key: ProjectKnowledgeCategory,
    expectedRevisionNo?: number,
  ) => Promise<KnowledgeCategoryRevision>;
  /**
   * Hand the project's knowledge authority to its category revisions: the
   * cutover that ends a single-page project's DIRECT_CONTEXT rendering. The
   * backend requires every category to hold an active revision or an explicit
   * clear before it accepts the call.
   */
  cutoverCategories: (projectId: string) => Promise<CategoryAuthorityState>;
  /** Store the original source file as a project knowledge document. */
  uploadDocument: (
    projectId: string,
    file: ProjectDocumentUpload,
  ) => Promise<ProjectTrainingDocument>;
  /**
   * Stateful-free text extraction of one source file (docx/md/txt): the
   * backend parses and returns the text without storing anything. A text
   * editor uses it to surface a .docx pick in place — the browser cannot
   * decode the OOXML container.
   */
  extractDocumentText: (file: ProjectDocumentUpload) => Promise<string>;
  getTrainingDocument: (documentId: string) => Promise<ProjectTrainingDocument>;
  getSinglePage: (projectId: string) => Promise<SinglePageKnowledge>;
  replaceSinglePage: (
    projectId: string,
    filename: string,
    text: string,
  ) => Promise<Omit<SinglePageKnowledge, "text"> & { text?: string }>;
  updateProjectDiscoveryCard: (
    projectId: string,
    patch: ProjectDiscoveryCardPatch,
  ) => Promise<Project>;
  getFeatures: (projectId: string) => Promise<ProductFeatureList>;
  extractFeatures: (projectId: string) => Promise<ProductFeatureList>;
  updateFeature: (
    projectId: string,
    featureId: string,
    patch: FeaturePatch,
  ) => Promise<ProductFeature>;
  getBusTimetable: (
    projectId: string,
    page: number,
    perPage: number,
  ) => Promise<BusTimetableList>;
  getFaq: (projectId: string, limit: number) => Promise<ProjectFaqList>;
  createFaq: (
    projectId: string,
    payload: ProjectFaqPayload,
  ) => Promise<ProjectFaq>;
  updateFaq: (
    projectId: string,
    faqId: string,
    payload: Partial<ProjectFaqPayload>,
  ) => Promise<ProjectFaq>;
  deleteFaq: (projectId: string, faqId: string) => Promise<void>;
}>;
