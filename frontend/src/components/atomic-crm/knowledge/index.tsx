import { lazy } from "react";
import type { KnowledgeSource } from "../types";

const KnowledgeSourceList = lazy(() =>
  import("./KnowledgeSourceList").then((m) => ({
    default: m.KnowledgeSourceList,
  })),
);
const KnowledgeSourceShow = lazy(() =>
  import("./KnowledgeSourceShow").then((m) => ({
    default: m.KnowledgeSourceShow,
  })),
);
const KnowledgeSourceEdit = lazy(() =>
  import("./KnowledgeSourceEdit").then((m) => ({
    default: m.KnowledgeSourceEdit,
  })),
);

// Admin view over the `knowledge_sources` table. Admins can upload documents,
// adjust their project assignment, retrain/archive, or delete bad uploads.
export default {
  list: KnowledgeSourceList,
  show: KnowledgeSourceShow,
  edit: KnowledgeSourceEdit,
  recordRepresentation: (record?: KnowledgeSource) =>
    record?.file_name ?? "Knowledge source",
};
