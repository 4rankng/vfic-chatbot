import type {
  ExternalSourceCreatePayload,
  FeaturePatch,
  ProjectFaqPayload,
  SinglePageExternalSourceCreatePayload,
} from "../domain/project-knowledge-contracts";
import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";
import type {
  CancellationSignal,
  ProjectDiscoveryCardPatch,
  ProjectDocumentUpload,
  ProjectKnowledgePort,
  ProjectTrainingWrite,
} from "./project-knowledge-port";

export const createProjectKnowledgeOperations = (port: ProjectKnowledgePort) =>
  Object.freeze({
    getCategories: (projectId: string) => port.getCategories(projectId),
    getCategoryTemplate: (projectId: string, key: ProjectKnowledgeCategory) =>
      port.getCategoryTemplate(projectId, key),
    getFullTemplate: (projectId: string) => port.getFullTemplate(projectId),
    getCategorySource: (projectId: string, key: ProjectKnowledgeCategory) =>
      port.getCategorySource(projectId, key),
    replaceCategory: (
      projectId: string,
      key: ProjectKnowledgeCategory,
      filename: string,
      content: string,
    ) => port.replaceCategory(projectId, key, filename, content),
    clearCategory: (projectId: string, key: ProjectKnowledgeCategory) =>
      port.clearCategory(projectId, key),
    cutoverCategories: (projectId: string) => port.cutoverCategories(projectId),
    uploadDocument: (
      projectId: string,
      file: ProjectDocumentUpload,
      writes?: readonly ProjectTrainingWrite[],
    ) => port.uploadDocument(projectId, file, writes),
    getTrainingDocument: (documentId: string) =>
      port.getTrainingDocument(documentId),
    getSinglePage: (projectId: string) => port.getSinglePage(projectId),
    replaceSinglePage: (projectId: string, filename: string, text: string) =>
      port.replaceSinglePage(projectId, filename, text),
    updateProjectDiscoveryCard: (
      projectId: string,
      patch: ProjectDiscoveryCardPatch,
    ) => port.updateProjectDiscoveryCard(projectId, patch),
    getFeatures: (projectId: string) => port.getFeatures(projectId),
    extractFeatures: (projectId: string) => port.extractFeatures(projectId),
    updateFeature: (
      projectId: string,
      featureId: string,
      patch: FeaturePatch,
    ) => port.updateFeature(projectId, featureId, patch),
    getBusTimetable: (projectId: string, page: number, perPage: number) =>
      port.getBusTimetable(projectId, page, perPage),
    getFaq: (projectId: string, limit: number) => port.getFaq(projectId, limit),
    createFaq: (projectId: string, payload: ProjectFaqPayload) =>
      port.createFaq(projectId, payload),
    updateFaq: (
      projectId: string,
      faqId: string,
      payload: Partial<ProjectFaqPayload>,
    ) => port.updateFaq(projectId, faqId, payload),
    deleteFaq: (projectId: string, faqId: string) =>
      port.deleteFaq(projectId, faqId),
    listExternalSources: (projectId: string, signal?: CancellationSignal) =>
      port.listExternalSources(projectId, signal),
    createExternalSource: (
      projectId: string,
      payload: ExternalSourceCreatePayload,
    ) => port.createExternalSource(projectId, payload),
    runExternalSourceNow: (projectId: string, sourceId: string) =>
      port.runExternalSourceNow(projectId, sourceId),
    deleteExternalSource: (projectId: string, sourceId: string) =>
      port.deleteExternalSource(projectId, sourceId),
    listSinglePageExternalSources: (
      projectId: string,
      signal?: CancellationSignal,
    ) => port.listSinglePageExternalSources(projectId, signal),
    createSinglePageExternalSource: (
      projectId: string,
      payload: SinglePageExternalSourceCreatePayload,
    ) => port.createSinglePageExternalSource(projectId, payload),
    runSinglePageExternalSourceNow: (projectId: string, sourceId: string) =>
      port.runSinglePageExternalSourceNow(projectId, sourceId),
    deleteSinglePageExternalSource: (projectId: string, sourceId: string) =>
      port.deleteSinglePageExternalSource(projectId, sourceId),
  });
