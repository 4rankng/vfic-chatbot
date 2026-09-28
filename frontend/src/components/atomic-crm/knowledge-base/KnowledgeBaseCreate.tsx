import {
  CreateBase,
  Form,
  useDataProvider,
  useNotify,
  useRedirect,
} from "ra-core";
import { useState } from "react";
import { useController } from "react-hook-form";
import { Input as UntitledInput } from "@/components/base/input/input";
import { Button } from "@/components/ui/button";
import { TextInput } from "@/components/admin/text-input";
import { SelectInput } from "@/components/admin/select-input";
import { ArrowLeft, BookOpen, Check, LoaderCircle } from "lucide-react";
import { Link } from "react-router";
import { PageHeading, PageShell } from "../kit";

/**
 * The name field renders an Untitled UI v8 (React Aria) input instead of the
 * react-admin one, to prove the library's components participate in a
 * react-admin form.
 *
 * `useController` is react-admin's own form engine (its `Form` is a
 * react-hook-form `FormProvider`), so this field is registered, validated and
 * submitted exactly like `TextInput` would be — no parallel form state.
 *
 * `uu-scope` is required, not decorative: outside it the four utility names the
 * console and Untitled UI both define (`bg-primary`, `bg-secondary`,
 * `text-primary`, `border-primary`) keep the console's meaning, and the field
 * would render with the brand coral fill instead of a white surface. See
 * `src/styles/untitledui-theme.css`.
 */
const KnowledgeBaseNameField = () => {
  const { field, fieldState } = useController({
    name: "name",
    rules: { required: true },
  });

  return (
    <UntitledInput
      className="uu-scope"
      name={field.name}
      ref={field.ref}
      value={typeof field.value === "string" ? field.value : ""}
      onChange={(value: string) => field.onChange(value)}
      onBlur={field.onBlur}
      label="Tên"
      placeholder="Ví dụ: VFIC tuyển dụng"
      isRequired
      isInvalid={fieldState.invalid}
      hint={fieldState.error ? "Tên kho là bắt buộc." : undefined}
    />
  );
};

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
          subtitle="Chọn chế độ truy cập dữ liệu."
          actions={
            <Button asChild variant="outline" size="sm">
              <Link to="/knowledge_bases">
                <ArrowLeft className="size-4" aria-hidden="true" />
                Kho kiến thức
              </Link>
            </Button>
          }
        />
        <section
          className="mt-4"
          aria-labelledby="knowledge-base-create-form-title"
        >
          <header className="flex items-start gap-3 border-y border-[var(--tt-border)] px-4 py-3">
            <BookOpen
              className="mt-0.5 size-5 shrink-0 text-muted-foreground"
              aria-hidden="true"
            />
            <div className="min-w-0">
              <h2
                id="knowledge-base-create-form-title"
                className="text-section-title font-semibold text-foreground"
              >
                Thông tin kho
              </h2>
              <p className="mt-1 text-helper text-muted-foreground">
                RAG cho nhiều dự án; trực tiếp cho một tệp.
              </p>
            </div>
          </header>

          <Form onSubmit={submit}>
            <div className="space-y-4 px-4 py-4">
              <KnowledgeBaseNameField />
              <TextInput source="slug" label="Slug" isRequired />
              <SelectInput
                source="mode"
                label="Chế độ"
                emptyText="Chọn chế độ"
                choices={[
                  { id: "RAG", name: "RAG — nhiều dự án" },
                  {
                    id: "DIRECT_CONTEXT",
                    name: "Trực tiếp — một tệp",
                  },
                ]}
                isRequired
              />
              <TextInput source="description" label="Mô tả" multiline />
              <div className="flex flex-wrap justify-end gap-2 border-t border-[var(--tt-border)] pt-4">
                <Button
                  type="button"
                  variant="outline"
                  className="min-h-11 sm:min-h-10"
                  disabled={saving}
                  onClick={() => redirect("list", "knowledge_bases")}
                >
                  Hủy
                </Button>
                <Button
                  type="submit"
                  disabled={saving}
                  className="min-h-11 sm:min-h-10"
                >
                  {saving ? (
                    <LoaderCircle
                      className="size-4 animate-spin motion-reduce:animate-none"
                      aria-hidden="true"
                    />
                  ) : (
                    <Check className="size-4" aria-hidden="true" />
                  )}
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
