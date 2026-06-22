import type { KnowledgeSource } from "../types";
import { KnowledgeSourceList } from "./KnowledgeSourceList";
import { KnowledgeSourceShow } from "./KnowledgeSourceShow";

// Read-only admin view over the `knowledge_sources` table (Drive-ingested RAG
// documents). Both roles can view; ingestion happens bot-side via the n8n
// Drive-sync workflow.
export default {
  list: KnowledgeSourceList,
  show: KnowledgeSourceShow,
  recordRepresentation: (record?: KnowledgeSource) =>
    record?.source_name ?? "Knowledge source",
};
