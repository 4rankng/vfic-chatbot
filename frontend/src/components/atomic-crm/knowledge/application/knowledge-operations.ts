import type {
  FileDownloadPort,
  KnowledgePort,
  KnowledgeUpload,
} from "./knowledge-port";

export const createKnowledgeOperations = (
  knowledge: KnowledgePort,
  downloads: FileDownloadPort,
) =>
  Object.freeze({
    createAndIngestVersion: async (
      projectId: string,
      file: KnowledgeUpload,
    ) => {
      const version = await knowledge.createVersion(projectId);
      await knowledge.uploadVersionFile(projectId, version.id, file);
      return knowledge.ingestVersion(projectId, version.id);
    },
    listVersions: knowledge.listVersions,
    publishVersion: knowledge.publishVersion,
    saveTemplate: async (kind: "knowledge" | "faq" = "knowledge") => {
      const content = await knowledge.downloadTemplate(kind);
      downloads.saveText(
        kind === "faq"
          ? "vfic-faq-v1-template.md"
          : "vfic-knowledge-v1-template.md",
        content,
        "text/markdown;charset=utf-8",
      );
    },
    saveRaw: async (documentId: string, filename = "knowledge-source.md") => {
      const content = await knowledge.downloadRaw(documentId);
      downloads.saveBinary(
        filename || "knowledge-source.md",
        content.bytes,
        content.mediaType,
      );
    },
    process: knowledge.process,
    archive: knowledge.archive,
    reindex: knowledge.reindex,
    reindexAll: knowledge.reindexAll,
    getUnits: knowledge.getUnits,
  });
