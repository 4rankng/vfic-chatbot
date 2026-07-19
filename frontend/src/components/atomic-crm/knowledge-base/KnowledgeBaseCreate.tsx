import { CreateBase, Form, useDataProvider, useNotify, useRedirect } from "ra-core";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { TextInput } from "@/components/admin/text-input";
import { SelectInput } from "@/components/admin/select-input";

export const KnowledgeBaseCreate = () => {
  const dataProvider = useDataProvider(); const notify = useNotify(); const redirect = useRedirect(); const [saving, setSaving] = useState(false);
  const submit = async (data: Record<string, unknown>) => { setSaving(true); try { await dataProvider.create("knowledge_bases", { data }); notify("Đã tạo Knowledge Base.", { type: "success" }); redirect("list", "knowledge_bases"); } catch (error) { notify((error as Error).message, { type: "error" }); } finally { setSaving(false); } };
    return <CreateBase resource="knowledge_bases"><div className="p-4 lg:p-6"><h1 className="text-page-title font-bold tracking-tight">Tạo Knowledge Base</h1><p className="mb-6 text-muted-foreground">Chọn RAG cho nhiều dự án; chọn ngữ cảnh trực tiếp cho một tệp văn bản gửi nguyên vẹn mỗi lượt.</p><Card className="max-w-xl"><CardContent className="pt-6"><Form onSubmit={submit}><div className="space-y-4"><TextInput source="name" label="Tên" isRequired /><TextInput source="slug" label="Slug" isRequired /><SelectInput source="mode" label="Chế độ" choices={[{ id: "RAG", name: "RAG — nhiều dự án, tệp và pipeline" }, { id: "DIRECT_CONTEXT", name: "Ngữ cảnh trực tiếp — một tệp văn bản" }]} isRequired /><TextInput source="description" label="Mô tả" multiline /><Button type="submit" disabled={saving}>{saving ? "Đang tạo..." : "Tạo Knowledge Base"}</Button></div></Form></CardContent></Card></div></CreateBase>;
};
