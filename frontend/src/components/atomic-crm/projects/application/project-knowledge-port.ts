import type {
  BusTimetableList,
  ProductFeature,
  ProductFeatureList,
} from "../../types";
import type {
  ExternalSourceCreatePayload,
  ExternalSourceSyncState,
  FeaturePatch,
  KnowledgeCategoryCatalog,
  KnowledgeCategoryRevision,
  KnowledgeCategorySource,
  KnowledgeCategoryTemplate,
  ProjectFaq,
  ProjectFaqList,
  ProjectFaqPayload,
  SinglePageExternalSourceCreatePayload,
  SinglePageExternalSourceSyncState,
  SinglePageKnowledge,
} from "../domain/project-knowledge-contracts";
import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";

export type CancellationSignal = Readonly<{
  aborted: boolean;
  onAbort: (listener: () => void) => () => void;
}>;
export type UploadFile = Readonly<{
  name: string;
  type: string;
  bytes: ArrayBuffer;
}>;

export type ProjectKnowledgePort = Readonly<{
  getCategories: (projectId: string) => Promise<KnowledgeCategoryCatalog>;
  getCategoryTemplate: (
    projectId: string,
    key: ProjectKnowledgeCategory,
  ) => Promise<KnowledgeCategoryTemplate>;
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
  uploadCategory: (
    projectId: string,
    key: ProjectKnowledgeCategory,
    file: UploadFile,
  ) => Promise<{ revision: KnowledgeCategoryRevision; job_id: string }>;
  getSinglePage: (projectId: string) => Promise<SinglePageKnowledge>;
  replaceSinglePage: (
    projectId: string,
    filename: string,
    text: string,
  ) => Promise<Omit<SinglePageKnowledge, "text"> & { text?: string }>;
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
  listExternalSources: (
    projectId: string,
    signal?: CancellationSignal,
  ) => Promise<ExternalSourceSyncState[]>;
  createExternalSource: (
    projectId: string,
    payload: ExternalSourceCreatePayload,
  ) => Promise<ExternalSourceSyncState>;
  runExternalSourceNow: (
    projectId: string,
    sourceId: string,
  ) => Promise<{ job_id: string }>;
  deleteExternalSource: (projectId: string, sourceId: string) => Promise<void>;
  listSinglePageExternalSources: (
    projectId: string,
    signal?: CancellationSignal,
  ) => Promise<SinglePageExternalSourceSyncState[]>;
  createSinglePageExternalSource: (
    projectId: string,
    payload: SinglePageExternalSourceCreatePayload,
  ) => Promise<SinglePageExternalSourceSyncState>;
  runSinglePageExternalSourceNow: (
    projectId: string,
    sourceId: string,
  ) => Promise<{ job_id: string }>;
  deleteSinglePageExternalSource: (
    projectId: string,
    sourceId: string,
  ) => Promise<void>;
}>;
