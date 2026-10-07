import { createProjectKnowledgeOperations } from "./application/project-knowledge-operations";
import type { CancellationSignal } from "./application/project-knowledge-port";
export type { ProjectTrainingDocument } from "./application/project-knowledge-port";
import type {
  FeaturePatch,
  KnowledgeCategoryCatalog,
  KnowledgeCategoryRevision,
  KnowledgeCategorySource,
  KnowledgeCategoryStatus,
  KnowledgeCategoryTemplate,
  ProjectFaq,
  ProjectFaqList,
  ProjectFaqPayload,
  SinglePageKnowledge,
} from "./domain/project-knowledge-contracts";
import type { ProjectKnowledgeCategory } from "./domain/project-knowledge-policy";
import { httpProjectKnowledgeAdapter } from "./infrastructure/http-project-knowledge-adapter";
export {
  PROJECT_TEXT_FILE_ACCEPT,
  assertProjectTextFile,
  readProjectBriefPreview,
} from "./infrastructure/project-text-file";

const operations = createProjectKnowledgeOperations(
  httpProjectKnowledgeAdapter,
);

const cancellationSignal = (signal: AbortSignal): CancellationSignal => ({
  get aborted() {
    return signal.aborted;
  },
  onAbort: (listener) => {
    signal.addEventListener("abort", listener, { once: true });
    return () => signal.removeEventListener("abort", listener);
  },
});

export const getProjectKnowledgeCategories = operations.getCategories;
export const getProjectKnowledgeCategoryTemplate =
  operations.getCategoryTemplate;
export const getProjectKnowledgeFullTemplate = (
  projectId: string,
  signal?: AbortSignal,
) =>
  operations.getFullTemplate(
    projectId,
    signal ? cancellationSignal(signal) : undefined,
  );
export const getProjectKnowledgeExport = (
  projectId: string,
  signal?: AbortSignal,
) =>
  operations.getKnowledgeExport(
    projectId,
    signal ? cancellationSignal(signal) : undefined,
  );
export const getProjectKnowledgeCategorySource = operations.getCategorySource;
export const replaceProjectKnowledgeCategory = operations.replaceCategory;
/**
 * Replace a category's active content with an explicit empty state — the
 * preparation a migration needs for the categories a brief does not carry, so
 * the cutover's "every category active or cleared" check can pass.
 */
export const clearProjectKnowledgeCategory = operations.clearCategory;
/** Hand the project's knowledge authority to its category revisions. */
export const cutoverProjectKnowledgeCategories = operations.cutoverCategories;
/**
 * Store the original source file as a project knowledge document — the brief
 * the chain parsed stays on record (retrievable, searchable) instead of only
 * surviving as derived category YAML.
 */
export const uploadProjectDocument = async (projectId: string, file: File) =>
  operations.uploadDocument(projectId, {
    name: file.name,
    type: file.type,
    bytes: await file.arrayBuffer(),
  });
/**
 * Server-side text extraction for one source file — nothing is stored. The
 * single-page editor converts a .docx pick through this before the save.
 */
export const extractProjectDocumentText = async (file: File) =>
  operations.extractDocumentText({
    name: file.name,
    type: file.type,
    bytes: await file.arrayBuffer(),
  });
export const getProjectTrainingDocument = operations.getTrainingDocument;
export const getProjectSinglePage = operations.getSinglePage;
export const replaceProjectSinglePage = operations.replaceSinglePage;
export const updateProjectDiscoveryCard = operations.updateProjectDiscoveryCard;
export const getProjectFeatures = operations.getFeatures;
export const extractProjectFeatures = operations.extractFeatures;
export const updateProjectFeature = operations.updateFeature;
export const getProjectFaq = operations.getFaq;
export const createProjectFaq = operations.createFaq;
export const updateProjectFaq = operations.updateFaq;
export const deleteProjectFaq = operations.deleteFaq;

export const getProjectBusTimetable = (
  projectId: string,
  { page = 1, perPage = 6 }: { page?: number; perPage?: number } = {},
) => operations.getBusTimetable(projectId, page, perPage);

export type {
  FeaturePatch,
  KnowledgeCategoryCatalog,
  KnowledgeCategoryRevision,
  KnowledgeCategorySource,
  KnowledgeCategoryStatus,
  KnowledgeCategoryTemplate,
  ProjectFaq,
  ProjectFaqList,
  ProjectFaqPayload,
  ProjectKnowledgeCategory as KnowledgeCategoryKey,
  SinglePageKnowledge,
};
