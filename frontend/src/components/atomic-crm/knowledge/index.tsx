import type { KnowledgeSource } from "../types";
import { KnowledgeSourceEdit } from "./KnowledgeSourceEdit";
import { KnowledgeSourceList } from "./KnowledgeSourceList";
import { KnowledgeSourceShow } from "./KnowledgeSourceShow";

// Admin view over the `knowledge_sources` table. Admins can upload documents,
// adjust their project assignment, retrain/archive, or delete bad uploads.
export default {
  list: KnowledgeSourceList,
  show: KnowledgeSourceShow,
  edit: KnowledgeSourceEdit,
  recordRepresentation: (record?: KnowledgeSource) =>
    record?.file_name ?? "Knowledge source",
};
