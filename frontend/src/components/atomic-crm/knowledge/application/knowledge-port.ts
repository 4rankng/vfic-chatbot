import type {
  KnowledgeBaseVersion,
  KnowledgeIngestResult,
  KnowledgeUnitList,
  ReindexAllKnowledgeResult,
} from "../domain/knowledge-contracts";

export type KnowledgeUpload = Readonly<{
  name: string;
  type: string;
  bytes: ArrayBuffer;
}>;
export type KnowledgeBinary = Readonly<{
  bytes: ArrayBuffer;
  mediaType: string;
}>;

export type KnowledgePort = Readonly<{
  createVersion: (projectId: string) => Promise<KnowledgeBaseVersion>;
  uploadVersionFile: (
    projectId: string,
    versionId: string,
    file: KnowledgeUpload,
  ) => Promise<Record<string, unknown>>;
  ingestVersion: (
    projectId: string,
    versionId: string,
  ) => Promise<KnowledgeIngestResult>;
  listVersions: (
    projectId: string,
  ) => Promise<{ data: KnowledgeBaseVersion[]; total: number }>;
  publishVersion: (
    projectId: string,
    versionId: string,
  ) => Promise<KnowledgeBaseVersion>;
  downloadTemplate: (kind: "knowledge" | "faq") => Promise<string>;
  downloadRaw: (documentId: string) => Promise<KnowledgeBinary>;
  process: (documentId: string) => Promise<Record<string, unknown>>;
  archive: (documentId: string) => Promise<Record<string, unknown>>;
  reindex: (documentId: string) => Promise<Record<string, unknown>>;
  reindexAll: () => Promise<ReindexAllKnowledgeResult>;
  getUnits: (documentId: string, limit: number) => Promise<KnowledgeUnitList>;
}>;

export type FileDownloadPort = Readonly<{
  saveText: (filename: string, content: string, mediaType: string) => void;
  saveBinary: (
    filename: string,
    bytes: ArrayBuffer,
    mediaType: string,
  ) => void;
}>;
