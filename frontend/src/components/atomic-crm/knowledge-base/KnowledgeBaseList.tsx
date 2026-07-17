import { ListBase, useListContext, useRedirect } from "ra-core";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { KnowledgeBase } from "../types";

const Content = () => {
  const { data = [], isPending } = useListContext<KnowledgeBase>();
  const redirect = useRedirect();
  return <div className="p-4 lg:p-6"><div className="mb-6 flex items-end justify-between gap-4"><div><h1 className="text-2xl font-bold tracking-tight">Knowledge Base</h1><p className="text-muted-foreground">Kho kiến thức dùng chung cho Agent.</p></div><Button onClick={() => redirect("create", "knowledge_bases")}>Tạo Knowledge Base</Button></div>{isPending ? <p className="text-muted-foreground">Đang tải...</p> : <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">{data.map((kb) => <Card key={kb.id}><CardHeader><CardTitle className="text-lg">{kb.name}</CardTitle><p className="text-sm text-muted-foreground">{kb.mode === "RAG" ? "RAG" : "Ngữ cảnh trực tiếp"}</p></CardHeader><CardContent><p className="text-sm">{kb.attached_agent_count} Agent · {kb.project_count} dự án</p><Button variant="outline" className="mt-4" onClick={() => redirect("show", "knowledge_bases", kb.id)}>Quản lý</Button></CardContent></Card>)}</div>}</div>;
};
export const KnowledgeBaseList = () => <ListBase resource="knowledge_bases" perPage={100} sort={{ field: "name", order: "ASC" }}><Content /></ListBase>;
