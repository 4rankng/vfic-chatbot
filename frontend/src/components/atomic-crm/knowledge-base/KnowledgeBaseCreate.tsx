import {
  CreateBase,
  Form,
  useDataProvider,
  useNotify,
  useRedirect,
} from "ra-core";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { TextInput } from "@/components/admin/text-input";
import { SelectInput } from "@/components/admin/select-input";
import { BookOpen, Check } from "lucide-react";
import { AlternateCard, PageHeading, PageShell } from "../kit";

export const KnowledgeBaseCreate = () => {
  const dataProvider = useDataProvider();
  const notify = useNotify();
  const redirect = useRedirect();
  const [saving, setSaving] = useState(false);
  const submit = async (data: Record<string, unknown>) => {
    setSaving(true);
    try {
      await dataProvider.create("knowledge_bases", { data });
      notify("Đã tạo Knowledge Base.", { type: "success" });
      redirect("list", "knowledge_bases");
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <CreateBase resource="knowledge_bases">
      <PageShell size="narrow">
        <PageHeading
          eyebrow="Thiết lập kho"
          title="Tạo kho kiến thức"
          subtitle="Chọn cách Agent truy cập dữ liệu trước khi thêm nội dung."
        />
        <AlternateCard
          className="mt-4"
          icon={<BookOpen className="size-4" aria-hidden="true" />}
          title="Thông tin cơ bản"
          description="RAG phù hợp nhiều dự án; ngữ cảnh trực tiếp phù hợp một tệp nguyên vẹn."
          bodyClassName="p-5 sm:p-6"
        >
          <Form onSubmit={submit}>
            <div className="space-y-5">
              <TextInput source="name" label="Tên" isRequired />
              <TextInput source="slug" label="Slug" isRequired />
              <SelectInput
                source="mode"
                label="Chế độ"
                choices={[
                  { id: "RAG", name: "RAG — nhiều dự án, tệp và pipeline" },
                  {
                    id: "DIRECT_CONTEXT",
                    name: "Ngữ cảnh trực tiếp — một tệp văn bản",
                  },
                ]}
                isRequired
              />
              <TextInput source="description" label="Mô tả" multiline />
              <div className="flex justify-end border-t border-[var(--tt-border)] pt-5">
                <Button
                  type="submit"
                  disabled={saving}
                  className="min-h-11 sm:min-h-10"
                >
                  <Check className="size-4" aria-hidden="true" />
                  {saving ? "Đang tạo…" : "Tạo kho kiến thức"}
                </Button>
              </div>
            </div>
          </Form>
        </AlternateCard>
      </PageShell>
    </CreateBase>
  );
};
