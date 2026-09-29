import { useEffect, useState } from "react";
import {
  CreateBase,
  Form,
  useDataProvider,
  useNotify,
  useRedirect,
} from "ra-core";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { X } from "lucide-react";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import {
  buildProjectCreation,
  parseCommaList,
  PROJECT_KNOWLEDGE_CATEGORY_LABELS,
} from "./domain/project-knowledge-policy";
import type { ProjectBrief } from "./domain/project-brief-ingest";
import {
  buildJobsYaml,
  planBriefKnowledge,
} from "./domain/project-knowledge-yaml";
import { slugifyVietnamese } from "./domain/vietnamese-slug";
import { ProjectBriefImport } from "./presentation/ProjectBriefImport";
import { useProjectIngest } from "./presentation/use-project-ingest";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";

type FieldProps = {
  id: string;
  label: string;
  value: string;
  placeholder?: string;
  required?: boolean;
  onChange: (value: string) => void;
};

const Field = ({
  id,
  label,
  value,
  placeholder,
  required,
  onChange,
}: FieldProps) => (
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

/** The brief's own words, shown so a mis-parsed section is visible rather than
 *  silently dropped. These never become form fields: the create schema refuses
 *  a discovery card on a RAG project ("RAG discovery cards are derived from
 *  active categories"), so the summary and location reach the assistant through
 *  the category YAML the pipeline writes, not through this form. */
const CarriedSummary = ({ brief }: { brief: ProjectBrief }) => (
  <dl className="project-brief-carried grid gap-1 text-helper text-muted-foreground">
    {brief.summary ? (
      <div>
        <dt className="inline font-medium text-foreground">Tóm tắt: </dt>
        <dd className="inline">{brief.summary}</dd>
      </div>
    ) : null}
    {brief.location ? (
      <div>
        <dt className="inline font-medium text-foreground">Địa điểm: </dt>
        <dd className="inline">{brief.location}</dd>
      </div>
    ) : null}
    {brief.highlights.length > 0 ? (
      <div>
        <dt className="inline font-medium text-foreground">Điểm nổi bật: </dt>
        <dd className="inline">{brief.highlights.join(", ")}</dd>
      </div>
    ) : null}
  </dl>
);

/** Owns the field values and the two-phase submit; renders `<Form>` around the
 *  body so react-admin's form context is available beneath the provider. */
const ProjectCreateForm = () => {
  const notify = useNotify();
  const redirect = useRedirect();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const { state, ingest, cancel } = useProjectIngest();

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [aliases, setAliases] = useState("");
  const [roles, setRoles] = useState("");
  const [brief, setBrief] = useState<ProjectBrief | null>(null);
  const [briefFilename, setBriefFilename] = useState("");
  /** The draft the pipeline is writing into. It exists from the moment a file
   *  is picked, because ingest needs a project to write to. */
  const [draftId, setDraftId] = useState<string | null>(null);
  /** Exactly the role list the `jobs` category was last written from, so the
   *  save step knows whether an edit still has to be pushed downstream. */
  const [ingestedRoles, setIngestedRoles] = useState("");
  const [creatingDraft, setCreatingDraft] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // The slug is derived, never typed: a hand-typed one contradicts the name it
  // is supposed to identify, and the brief's own slug loses to the name the
  // recruiter actually typed above it.
  useEffect(() => {
    if (name.trim()) setSlug(slugifyVietnamese(name));
  }, [name]);

  useEffect(() => cancel, [cancel]);

  /**
   * Picking a file IS the start of the pipeline.
   *
   * The draft is created first and stays inactive, because the knowledge API is
   * keyed by project and there is nothing to ingest into until it exists. The
   * recruiter still reviews everything and still presses `Tạo dự án`; what
   * moved is only WHEN the work starts, not WHO decides it counts.
   */
  const onImported = async (parsed: ProjectBrief, filename: string) => {
    setBrief(parsed);
    setBriefFilename(filename);
    if (parsed.aliases.length > 0) setAliases(parsed.aliases.join(", "));
    if (parsed.roles.length > 0) setRoles(parsed.roles.join(", "));
    // The typed name wins: the pipeline fills what the recruiter left empty,
    // never overwrites a decision already made.
    if (!name.trim() && parsed.name) setName(parsed.name);

    setCreatingDraft(true);
    try {
      const created = await dataProvider.create("projects", {
        data: {
          name: (name.trim() || parsed.name || "Dự án mới").trim(),
          slug: slugifyVietnamese(name.trim() || parsed.name || "du-an-moi"),
          ...buildProjectCreation({ aliases: parsed.aliases.join(", ") }),
        },
      });
      const id = String(created.data.id);
      setDraftId(id);
      setIngestedRoles(parsed.roles.join(", "));
      await ingest(id, planBriefKnowledge(parsed).writes);
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setCreatingDraft(false);
    }
  };

  const rolesDirty = roles.trim() !== ingestedRoles.trim();

  /**
   * `Tạo dự án` activates the draft. It never half-activates: if activation is
   * refused, the exact backend reason is shown and the project stays inactive
   * and invisible to candidates, rather than going live on a guess.
   */
  const onSubmit = async () => {
    if (!draftId) return;
    const roleList = parseCommaList(roles);
    if (roleList.length === 0) {
      notify("Cần ít nhất một vị trí tuyển dụng để dự án có thể hoạt động.", {
        type: "warning",
      });
      return;
    }
    setSubmitting(true);
    try {
      // An edited role list is a real change to the knowledge, so it is written
      // before the project is allowed to go live — otherwise the live project
      // would answer with roles the recruiter just removed.
      if (rolesDirty) {
        await ingest(draftId, [
          {
            key: "jobs",
            filename: "jobs.yaml",
            content: buildJobsYaml(roleList),
          },
        ]);
        setIngestedRoles(roles.trim());
      }
      await dataProvider.update("projects", {
        id: draftId,
        data: {
          name: name.trim(),
          aliases: parseCommaList(aliases),
          is_active: true,
        },
        previousData: { id: draftId },
      });
      notify("Đã tạo dự án. Kiến thức đã sẵn sàng cho Agent.", {
        type: "success",
      });
      redirect("show", "projects", draftId);
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  const ingesting = state.phase === "running";
  const canSave =
    draftId !== null && !ingesting && !creatingDraft && !submitting;
  const ingestBlocked = state.phase === "failed";

  return (
    <Form onSubmit={onSubmit}>
      <div className="flex flex-col gap-4">
        <Field
          id="project-name"
          label="Tên dự án"
          value={name}
          placeholder="LG Display Hải Phòng"
          required
          onChange={setName}
        />
        <Field
          id="project-slug"
          label="Mã dự án"
          value={slug}
          placeholder="lg-display-hai-phong"
          onChange={setSlug}
        />
        <Field
          id="project-aliases"
          label="Tên gọi khác"
          value={aliases}
          placeholder="LG, LGD (không bắt buộc)"
          onChange={setAliases}
        />
        <Field
          id="project-roles"
          label="Vị trí tuyển dụng"
          value={roles}
          placeholder="Công nhân sản xuất, Kiểm tra"
          required
          onChange={setRoles}
        />
        <p className="text-helper text-muted-foreground">
          Mỗi vị trí là một dòng trong danh mục «Vị trí tuyển dụng». Dự án cần
          ít nhất một vị trí thì Agent mới tư vấn được. Số lượng tuyển không
          giới hạn nên không cần khai báo.
        </p>

        <hr className="border-border" />

        <ProjectBriefImport
          brief={brief}
          filename={briefFilename}
          busy={creatingDraft || ingesting}
          onImported={(parsed, filename) => void onImported(parsed, filename)}
        />

        {brief ? <CarriedSummary brief={brief} /> : null}

        {state.phase === "running" ? (
          <p role="status" className="text-helper text-foreground">
            Đang nạp «{PROJECT_KNOWLEDGE_CATEGORY_LABELS[state.current]}» (
            {state.activated.length + 1}/{state.total})…
          </p>
        ) : null}
        {state.phase === "done" ? (
          <p role="status" className="text-helper text-foreground">
            Đã nạp xong {state.activated.length} phần kiến thức. Bạn có thể kiểm
            tra rồi tạo dự án.
          </p>
        ) : null}
        {ingestBlocked ? (
          <p role="alert" className="text-helper text-destructive">
            Nạp «{PROJECT_KNOWLEDGE_CATEGORY_LABELS[state.failed]}» không thành
            công
            {state.message ? `: ${state.message}` : "."} Dự án vẫn là bản nháp
            và chưa hiển thị với ứng viên. Sửa nội dung rồi tải lại tệp.
          </p>
        ) : null}
        {rolesDirty && draftId ? (
          <p className="text-helper text-muted-foreground">
            Danh sách vị trí đã sửa — sẽ được nạp lại khi bạn bấm «Tạo dự án».
          </p>
        ) : null}

        <p className="text-helper text-muted-foreground">
          Dự án chỉ hiển thị với ứng viên sau khi bạn bấm «Tạo dự án».
        </p>
        <Button type="submit" disabled={!canSave}>
          {submitting ? "Đang tạo…" : "Tạo dự án"}
        </Button>
      </div>
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
