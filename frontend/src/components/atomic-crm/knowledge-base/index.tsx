import { lazy } from "react";
import type { KnowledgeBase } from "../types";

const KnowledgeBaseList = lazy(() => import("./KnowledgeBaseList").then((m) => ({ default: m.KnowledgeBaseList })));
const KnowledgeBaseCreate = lazy(() => import("./KnowledgeBaseCreate").then((m) => ({ default: m.KnowledgeBaseCreate })));
const KnowledgeBaseShow = lazy(() => import("./KnowledgeBaseShow").then((m) => ({ default: m.KnowledgeBaseShow })));

export default { list: KnowledgeBaseList, create: KnowledgeBaseCreate, show: KnowledgeBaseShow, recordRepresentation: (record?: KnowledgeBase) => record?.name ?? "Knowledge Base" };
