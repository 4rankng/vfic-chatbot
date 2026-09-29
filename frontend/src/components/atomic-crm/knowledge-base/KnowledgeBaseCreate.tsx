import {
  CreateBase,
  Form,
  useDataProvider,
  useNotify,
  useRedirect,
} from "ra-core";
import { useHref } from "react-router";
import { useState } from "react";
import { required } from "ra-core";
import { Button } from "@/components/base/buttons/button";
import { ArrowLeft, BookOpen } from "lucide-react";
import {
  FormSelect,
  FormTextArea,
  FormTextInput,
  PageHeading,
  PageShell,
} from "../kit";

/** The two access modes, as choices for the kit's select. Copy is unchanged. */
const KNOWLEDGE_BASE_MODES = [
  { id: "RAG", name: "RAG — nhiều dự án" },
  { id: "DIRECT_CONTEXT", name: "Trực tiếp — một tệp" },
];

const REQUIRED_FIELD = required("Vui lòng nhập thông tin.");

/**
 * Create form for a knowledge base.
 *
 * The fields are the kit's react-admin bound controls on Untitled UI v8 inputs,
 * so this page carries no form markup of its own: `useInput` registers each
 * field with react-admin's form engine, and the controls pin
 * `validationBehavior="aria"` so the browser never pre-empts the console's
 * Vietnamese validation with a native bubble.
 */
export const KnowledgeBaseCreate = () => {
  const dataProvider = useDataProvider();
  const notify = useNotify();
  const redirect = useRedirect();
  const [saving, setSaving] = useState(false);
  const listHref = useHref("/knowledge_bases");
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
          subtitle="Chọn chế độ truy cập dữ liệu."
          actions={
            <Button
              href={listHref}
              color="secondary"
              size="sm"
              iconLeading={ArrowLeft}
            >
              Kho kiến thức
            </Button>
          }
        />
        <section
          className="mt-4"
          aria-labelledby="knowledge-base-create-form-title"
        >
          <header className="flex items-start gap-3 border-y border-secondary px-4 py-3">
            <BookOpen
              className="mt-0.5 size-5 shrink-0 text-tertiary"
              aria-hidden="true"
            />
            <div className="min-w-0">
              <h2
                id="knowledge-base-create-form-title"
                className="text-section-title font-semibold text-primary"
              >
                Thông tin kho
              </h2>
              <p className="mt-1 text-[length:var(--fs-helper)] text-tertiary">
                RAG cho nhiều dự án; trực tiếp cho một tệp.
              </p>
            </div>
          </header>

          <Form onSubmit={submit}>
            <div className="space-y-4 px-4 py-4">
              <FormTextInput
                source="name"
                label="Tên"
                placeholder="Ví dụ: VFIC tuyển dụng"
                isRequired
                validate={REQUIRED_FIELD}
              />
              <FormTextInput
                source="slug"
                label="Slug"
                isRequired
                validate={REQUIRED_FIELD}
              />
              <FormSelect
                source="mode"
                label="Chế độ"
                choices={KNOWLEDGE_BASE_MODES}
                placeholder="Chọn chế độ"
                isRequired
                validate={REQUIRED_FIELD}
              />
              <FormTextArea
                source="description"
                label="Mô tả"
                rows={4}
              />
              <div className="flex flex-wrap justify-end gap-2 border-t border-secondary pt-4">
                <Button
                  color="secondary"
                  size="md"
                  className="min-h-11"
                  onClick={() => redirect("list", "knowledge_bases")}
                  isDisabled={saving}
                >
                  Hủy
                </Button>
                <Button
                  type="submit"
                  size="md"
                  className="min-h-11"
                  isDisabled={saving}
                  isLoading={saving}
                  showTextWhileLoading
                >
                  {saving ? "Đang tạo…" : "Tạo kho kiến thức"}
                </Button>
              </div>
            </div>
          </Form>
        </section>
      </PageShell>
    </CreateBase>
  );
};
