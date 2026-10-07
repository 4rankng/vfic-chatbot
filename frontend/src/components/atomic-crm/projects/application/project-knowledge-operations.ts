import type {
  FeaturePatch,
  ProjectFaqPayload,
} from "../domain/project-knowledge-contracts";
import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";
import type {
  CancellationSignal,
  ProjectDiscoveryCardPatch,
  ProjectDocumentUpload,
  ProjectKnowledgePort,
} from "./project-knowledge-port";

export const createProjectKnowledgeOperations = (port: ProjectKnowledgePort) =>
  Object.freeze({
    getCategories: (projectId: string) => port.getCategories(projectId),
    getCategoryTemplate: (projectId: string, key: ProjectKnowledgeCategory) =>
      port.getCategoryTemplate(projectId, key),
    getFullTemplate: (projectId: string, signal?: CancellationSignal) =>
      port.getFullTemplate(projectId, signal),
    getKnowledgeExport: (projectId: string, signal?: CancellationSignal) =>
      port.getKnowledgeExport(projectId, signal),
    getCategorySource: (projectId: string, key: ProjectKnowledgeCategory) =>
      port.getCategorySource(projectId, key),
    replaceCategory: (
      projectId: string,
      key: ProjectKnowledgeCategory,
      filename: string,
      content: string,
    ) => port.replaceCategory(projectId, key, filename, content),
    clearCategory: (
      projectId: string,
      key: ProjectKnowledgeCategory,
      expectedRevisionNo?: number,
    ) => port.clearCategory(projectId, key, expectedRevisionNo),
    cutoverCategories: (projectId: string) => port.cutoverCategories(projectId),
    uploadDocument: (projectId: string, file: ProjectDocumentUpload) =>
      port.uploadDocument(projectId, file),
    extractDocumentText: (file: ProjectDocumentUpload) =>
      port.extractDocumentText(file),
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
  });
