import { useState } from "react";
import {
  CreateBase,
  Form,
  useDataProvider,
  useNotify,
  useRedirect,
} from "ra-core";
import { TextInput } from "@/components/admin/text-input";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { X } from "lucide-react";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import {
  buildProjectCreation,
  type ProjectKnowledgeMode,
} from "./domain/project-knowledge-policy";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";

type KnowledgeModeOptionProps = {
  value: ProjectKnowledgeMode;
  selected: boolean;
  title: string;
  description: string;
  onSelect: (value: ProjectKnowledgeMode) => void;
};

const KnowledgeModeOption = ({
  value,
  selected,
  title,
  description,
  onSelect,
}: KnowledgeModeOptionProps) => {
  const descriptionId = `knowledge-mode-${value.toLowerCase()}-description`;

  return (
    <label
      className={cn("project-mode-option", selected && "is-selected")}
      data-selected={selected ? "true" : "false"}
    >
      <input
        className="sr-only"
        type="radio"
        name="knowledge-mode"
        value={value}
        checked={selected}
        aria-describedby={descriptionId}
        onChange={() => onSelect(value)}
      />
      <span className="project-mode-indicator" aria-hidden="true">
        <span />
      </span>
      <span className="min-w-0">
        <span className="block font-semibold text-foreground">{title}</span>
        <span
          id={descriptionId}
          className="mt-1 block text-helper text-muted-foreground"
        >
          {description}
        </span>
      </span>
    </label>
  );
};

type ProjectInputFieldProps = {
  id: string;
  label: string;
  value: string;
  placeholder: string;
  required?: boolean;
  onChange: (value: string) => void;
};

const ProjectInputField = ({
  id,
  label,
  value,
  placeholder,
  required = false,
  onChange,
}: ProjectInputFieldProps) => (
  <div className="grid gap-1.5">
    <label htmlFor={id} className="text-sm font-medium text-foreground">
      {label}
      {required ? <span aria-hidden="true"> *</span> : null}
    </label>
    <Input
      id={id}
      value={value}
      required={required}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
    />
  </div>
);

export const ProjectCreate = () => {
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [submitting, setSubmitting] = useState(false);
  const [mode, setMode] = useState<"" | ProjectKnowledgeMode>("");
  const [aliases, setAliases] = useState("");
  const [summary, setSummary] = useState("");
  const [location, setLocation] = useState("");
  const [roles, setRoles] = useState("");
  const [highlights, setHighlights] = useState("");

  const onSubmit = async (data: Record<string, unknown>) => {
    setSubmitting(true);
    try {
      const creation = buildProjectCreation({
        aliases,
        mode,
        discovery: { summary, location, roles, highlights },
      });
      if (!creation.ok && creation.reason === "mode_required") {
        notify("Chọn một cách lưu kiến thức để tiếp tục.", { type: "warning" });
        setSubmitting(false);
        return;
      }
      if (!creation.ok) {
        notify(
          "Vui lòng nhập tóm tắt và địa điểm để Agent có thể gợi ý dự án.",
          {
            type: "warning",
          },
        );
        setSubmitting(false);
        return;
      }
      const created = await dataProvider.create("projects", {
        data: {
          ...data,
          ...creation.data,
        },
      });
      notify("Đã tạo dự án.", { type: "success" });
      redirect("edit", "projects", created.data.id);
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <CreateBase resource="projects">
      <ProjectWorkspaceShell>
        <div className="project-workspace-content">
          <div className="project-create-shell mx-auto w-full max-w-4xl">
            <header className="project-editor-header project-form-page-header flex flex-wrap items-start gap-4">
              <div className="mr-auto min-w-0">
                <p className="text-helper font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  Dự án
                </p>
                <h1 className="mt-1 text-content-title font-semibold">
                  Tạo dự án
                </h1>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => redirect("/projects")}
                aria-label="Đóng và quay lại danh sách dự án"
              >
                <X className="size-4" aria-hidden="true" />
                Đóng
              </Button>
            </header>
            <div className="project-form-surface">
              <Form onSubmit={onSubmit}>
                <div className="flex flex-col gap-4">
                  <TextInput source="name" label="Tên dự án" isRequired />
                  <TextInput
                    source="slug"
                    label="Mã dự án"
                    helperText="Không dấu hoặc khoảng trắng."
                    placeholder="lg-display-hai-phong"
                    isRequired
                  />
                  <fieldset
                    className="project-mode-fieldset grid gap-3"
                    aria-required="true"
                  >
                    <legend className="font-medium">
                      Cách quản lý kiến thức
                      <span aria-hidden="true"> *</span>
                    </legend>
                    <div className="project-mode-grid">
                      <KnowledgeModeOption
                        value="DIRECT_CONTEXT"
                        selected={mode === "DIRECT_CONTEXT"}
                        title="Một nội dung"
                        description="Nhanh gọn; cập nhật toàn bộ cùng lúc."
                        onSelect={setMode}
                      />
                      <KnowledgeModeOption
                        value="RAG"
                        selected={mode === "RAG"}
                        title="Theo danh mục"
                        description="12 phần riêng; dễ cập nhật từng nội dung."
                        onSelect={setMode}
                      />
                    </div>
                    <p className="text-helper text-muted-foreground">
                      Không đổi được sau khi có dữ liệu.
                    </p>
                  </fieldset>
                  <ProjectInputField
                    id="project-aliases"
                    label="Tên gọi khác"
                    value={aliases}
                    placeholder="LG, LGD (không bắt buộc)"
                    onChange={setAliases}
                  />
                  {mode === "DIRECT_CONTEXT" && (
                    <section
                      className="project-discovery-section grid gap-3"
                      aria-labelledby="project-discovery-title"
                    >
                      <h2
                        id="project-discovery-title"
                        className="font-medium text-foreground"
                      >
                        Giúp ứng viên tìm đúng dự án
                      </h2>
                      <ProjectInputField
                        id="project-summary"
                        label="Tóm tắt"
                        value={summary}
                        placeholder="Dự án tuyển dụng nào?"
                        required
                        onChange={setSummary}
                      />
                      <div className="grid gap-3 sm:grid-cols-2">
                        <ProjectInputField
                          id="project-location"
                          label="Địa điểm"
                          value={location}
                          placeholder="Hải Phòng"
                          required
                          onChange={setLocation}
                        />
                        <ProjectInputField
                          id="project-roles"
                          label="Vị trí tuyển dụng"
                          value={roles}
                          placeholder="Sản xuất, kiểm tra"
                          onChange={setRoles}
                        />
                      </div>
                      <ProjectInputField
                        id="project-highlights"
                        label="Điểm nổi bật"
                        value={highlights}
                        placeholder="Không yêu cầu kinh nghiệm"
                        onChange={setHighlights}
                      />
                    </section>
                  )}
                  <p className="text-helper text-muted-foreground">
                    Dự án chỉ hiển thị sau khi có kiến thức.
                  </p>
                  <Button type="submit" disabled={submitting}>
                    Tạo dự án
                  </Button>
                </div>
              </Form>
            </div>
          </div>
        </div>
      </ProjectWorkspaceShell>
    </CreateBase>
  );
};
