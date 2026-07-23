import { createKnowledgeOperations } from "./application/knowledge-operations";
import type { KnowledgeUpload } from "./application/knowledge-port";
import type {
  KnowledgeBaseVersion,
  KnowledgeUnit,
  KnowledgeUnitList,
  ReindexAllKnowledgeResult,
} from "./domain/knowledge-contracts";
import { browserFileDownloadAdapter } from "./infrastructure/browser-file-download-adapter";
import { httpKnowledgeAdapter } from "./infrastructure/http-knowledge-adapter";

const operations = createKnowledgeOperations(
  httpKnowledgeAdapter,
  browserFileDownloadAdapter,
);

const upload = async (file: File): Promise<KnowledgeUpload> => ({
  name: file.name,
  type: file.type,
  bytes: await file.arrayBuffer(),
});

export const createAndIngestKnowledgeBaseVersion = async (
  projectId: string,
  file: File,
) => operations.createAndIngestVersion(projectId, await upload(file));
export const listKnowledgeBaseVersions = operations.listVersions;
export const publishKnowledgeBaseVersion = operations.publishVersion;
export const saveKnowledgeTemplate = operations.saveTemplate;
export const downloadKnowledgeRawFile = operations.saveRaw;
export const processKnowledge = operations.process;
export const archiveKnowledge = operations.archive;
export const reindexKnowledge = operations.reindex;
export const reindexAllKnowledge = operations.reindexAll;
export const getKnowledgeUnits = (
  documentId: string,
  limit = 50,
) => operations.getUnits(documentId, limit);

export type {
  KnowledgeBaseVersion,
  KnowledgeUnit,
  KnowledgeUnitList,
  ReindexAllKnowledgeResult,
};
