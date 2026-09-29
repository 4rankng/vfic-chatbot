import { useState } from "react";
import {
  CreateBase,
  Form,
  useDataProvider,
  useNotify,
  useRedirect,
} from "ra-core";
import { useFormContext } from "react-hook-form";
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
import type { ProjectBrief } from "./domain/project-brief-ingest";
import { planBriefKnowledge } from "./domain/project-knowledge-yaml";
import { ProjectBriefImport } from "./presentation/ProjectBriefImport";
import {
  replaceProjectKnowledgeCategory,
  replaceProjectSinglePage,
} from "./project-knowledge-service";
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
}: KnowledgeModeOptionProps) => (
  <label
    className={cn(
      "project-mode-option flex cursor-pointer items-start gap-2 rounded-lg border p-3",
      selected && "border-brand bg-brand-subtle",
    )}
    data-selected={selected ? "true" : undefined}
  >
    <input
      type="radio"
      name="project-knowledge-mode"
      className="sr-only"
      checked={selected}
      onChange={() => onSelect(value)}
    />
    <span className="grid gap-0.5">
      <span className="font-medium text-foreground">{title}</span>
      <span className="text-helper text-muted-foreground">{description}</span>
    </span>
  </label>
);

type ProjectInputFieldProps = {
  id: string;
  label: string;
  value: string;
  placeholder?: string;
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
    <label htmlFor={id} className="font-medium">
      {label}
      {required ? <span aria-hidden="true"> *</span> : null}
    </label>
    <Input
      id={id}
      value={value}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
    />
  </div>
);

/** Everything the submit path needs, kept out of the presentational body. */
type ProjectFormState = {
  mode: "" | ProjectKnowledgeMode;
  setMode: (value: ProjectKnowledgeMode) => void;
  aliases: string;
  setAliases: (value: string) => void;
  summary: string;
  setSummary: (value: string) => void;
  location: string;
  setLocation: (value: string) => void;
  roles: string;
  setRoles: (value: string) => void;
  highlights: string;
  setHighlights: (value: string) => void;
  brief: ProjectBrief | null;
  briefFilename: string;
  onBrief: (brief: ProjectBrief, filename: string) => void;
  submitting: boolean;
};

/**
 * The form BODY, rendered as `<Form>`'s child.
 *
 * It lives below the provider on purpose: the brief import writes the project
 * name and slug through `useFormContext().setValue`, and that context exists
 * only beneath react-admin's `<Form>`. Reading it from any component above it
 * silently yields `null` — which the component test pins.
 *
 * The values it edits are owned by `ProjectCreateForm` above; this component
 * presents them and hands the parsed brief back up to be remembered.
 */
const ProjectCreateFieldset = ({
  mode,
  setMode,
  aliases,
  setAliases,
  summary,
  setSummary,
  location,
  setLocation,
  roles,
  setRoles,
  highlights,
  setHighlights,
  brief,
  briefFilename,
  onBrief,
  submitting,
}: ProjectFormState) => {
  const { setValue } = useFormContext();

  const applyBrief = (parsed: ProjectBrief, filename: string) => {
    onBrief(parsed, filename);
    if (parsed.name) {
      setValue("name", parsed.name);
      if (parsed.slug) setValue("slug", parsed.slug);
    }
    if (parsed.aliases.length > 0) setAliases(parsed.aliases.join(", "));
    if (parsed.summary) setSummary(parsed.summary);
    if (parsed.location) setLocation(parsed.location);
    if (parsed.roles.length > 0) setRoles(parsed.roles.join(", "));
    if (parsed.highlights.length > 0)
      setHighlights(parsed.highlights.join(", "));
    // The brief proposes the mode; the recruiter can still switch it, and an
    // empty field is never overwritten by a blank.
    if (parsed.knowledgeMode) setMode(parsed.knowledgeMode);
  };

  return (
    <div className="flex flex-col gap-4">
      <ProjectBriefImport
        brief={brief}
        filename={briefFilename}
        onImported={applyBrief}
      />
      <hr className="border-border" />
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
  );
};

type SeedOutcome = Readonly<{
  failed: number;
  seeded: number;
  needsHuman: number;
}>;

/** Owns the field values and the submit path; renders `<Form>` around the body. */
const ProjectCreateForm = () => {
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
  const [brief, setBrief] = useState<ProjectBrief | null>(null);
  const [briefFilename, setBriefFilename] = useState("");

  /**
   * Seed what the brief genuinely carries.
   *
   * The RAG categories are TYPED YAML, not prose: the API rejects a `.md` body
   * outright, and a category like `jobs` wants fields (vacancies, employment
   * type) the brief never states. So only the FAQ is seeded — its question and
   * answer are verbatim from the file — and the rest is reported so the
   * recruiter knows what still needs a human instead of opening an empty
   * category later.
   *
   * A failure never loses the project: it already exists, so the write is
   * reported and the recruiter lands on the edit page to finish the rest.
   */
  const seedKnowledge = async (
    projectId: string,
    parsed: ProjectBrief,
    knowledgeMode: ProjectKnowledgeMode,
    filename: string,
  ): Promise<SeedOutcome> => {
    if (knowledgeMode !== "RAG") {
      try {
        await replaceProjectSinglePage(projectId, filename, parsed.rawText);
        return { failed: 0, seeded: 1, needsHuman: 0 };
      } catch {
        return { failed: 1, seeded: 0, needsHuman: 0 };
      }
    }
    const plan = planBriefKnowledge(parsed.faqEntries);
    let failed = 0;
    for (const write of plan.writes) {
      try {
        await replaceProjectKnowledgeCategory(
          projectId,
          write.key,
          write.filename,
          write.content,
        );
      } catch {
        failed += 1;
      }
    }
    return {
      failed,
      seeded: plan.writes.length,
      needsHuman: plan.needsHuman.length,
    };
  };

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
      const projectId = String(created.data.id);
      if (brief) {
        const { failed, seeded, needsHuman } = await seedKnowledge(
          projectId,
          brief,
          creation.data.knowledge_mode,
          briefFilename,
        );
        if (failed > 0) {
          notify(
            `Đã tạo dự án nhưng ${failed} phần kiến thức chưa lưu được. Mở trang kiến thức để thử lại.`,
            { type: "warning" },
          );
        } else if (needsHuman > 0) {
          notify(
            `Đã tạo dự án và nạp ${seeded} mục kiến thức từ tệp. ${needsHuman} mục còn lại cần nhập tay vì tệp không có dữ liệu dạng trường.`,
            { type: "success" },
          );
        } else {
          notify("Đã tạo dự án kèm kiến thức từ tệp.", { type: "success" });
        }
      } else {
        notify("Đã tạo dự án.", { type: "success" });
      }
      redirect("edit", "projects", projectId);
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Form onSubmit={onSubmit}>
      <ProjectCreateFieldset
        mode={mode}
        setMode={setMode}
        aliases={aliases}
        setAliases={setAliases}
        summary={summary}
        setSummary={setSummary}
        location={location}
        setLocation={setLocation}
        roles={roles}
        setRoles={setRoles}
        highlights={highlights}
        setHighlights={setHighlights}
        brief={brief}
        briefFilename={briefFilename}
        onBrief={(parsed, filename) => {
          setBrief(parsed);
          setBriefFilename(filename);
        }}
        submitting={submitting}
      />
    </Form>
  );
};

export const ProjectCreate = () => {
  const redirect = useRedirect();
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
              <ProjectCreateForm />
            </div>
          </div>
        </div>
      </ProjectWorkspaceShell>
    </CreateBase>
  );
};
