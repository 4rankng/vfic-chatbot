import { useEffect, useState } from "react";
import {
  CreateBase,
  Form,
  useDataProvider,
  useNotify,
  useRedirect,
} from "ra-core";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
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
import { updateProjectDiscoveryCard } from "./project-knowledge-service";
import { IngestProgressBoard } from "./presentation/IngestProgressBoard";
import { ProjectBriefImport } from "./presentation/ProjectBriefImport";
import { useProjectIngest } from "./presentation/use-project-ingest";
import { ProjectWorkspaceShell } from "./ProjectWorkspaceShell";

/** The brief's own words, shown so a mis-parsed section is visible rather than
 *  silently dropped. These never become form fields: the create schema refuses
 *  a discovery card on a RAG project ("RAG discovery cards are derived from
 *  active categories"), so the summary and location reach the assistant through
 *  the category YAML the pipeline writes, not through this form. The highlights
 *  are the one card key the chain does carry — see the PATCH in `onImported`. */
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
  const onImported = async (
    parsed: ProjectBrief,
    filename: string,
    file: File,
  ) => {
    setBrief(parsed);
    setBriefFilename(filename);
    if (parsed.aliases.length > 0) setAliases(parsed.aliases.join(", "));
    if (parsed.roles.length > 0) setRoles(parsed.roles.join(", "));
    // The typed name wins: the pipeline fills what the recruiter left empty,
    // never overwrites a decision already made.
    if (!name.trim() && parsed.name) setName(parsed.name);

    setCreatingDraft(true);
    try {
      // A re-picked file must update the draft the earlier pick created — a
      // second draft would strand the first — and then re-run the whole chain
      // from the NEW parse: every category the file carries is written again
      // and supersedes its previous revision, and the new file joins the
      // project documents.
      let id = draftId;
      if (!id) {
        const created = await dataProvider.create("projects", {
          data: {
            name: (name.trim() || parsed.name || "Dự án mới").trim(),
            slug: slugifyVietnamese(name.trim() || parsed.name || "du-an-moi"),
            ...buildProjectCreation({ aliases: parsed.aliases.join(", ") }),
          },
        });
        id = String(created.data.id);
        setDraftId(id);
      }
      // The brief's highlight facts ride the card itself: PATCHed right after
      // the draft exists and before the category writes, because the
      // activation projection PRESERVES `highlights` (it only seeds them), so
      // landing them first is safe and no later projection clobbers them. A
      // brief with no highlights sends nothing — the card keeps its derived
      // empty list.
      if (parsed.highlights.length > 0) {
        await updateProjectDiscoveryCard(id, {
          discovery_card: { highlights: parsed.highlights },
        });
      }
      setIngestedRoles(parsed.roles.join(", "));
      await ingest(id, planBriefKnowledge(parsed).writes, file);
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
   * and invisible to candidates, rather than going live on a guess. The form
   * itself demands nothing beyond the name and the file — the roles are filled
   * from the brief and stay optional, so no role gate stands between the admin
   * and this button.
   */
  const onSubmit = async () => {
    if (!draftId) return;
    const roleList = parseCommaList(roles);
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
  // The brief-document upload is best-effort: its error is shown alongside the
  // outcome, never as a reason to block the category writes or the activation.
  const uploadError =
    state.phase === "done" || state.phase === "failed"
      ? state.uploadError
      : undefined;

  return (
    <Form onSubmit={onSubmit}>
      <div className="flex flex-col gap-4">
        <Input
          id="project-name"
          className="uu-scope"
          label="Tên dự án"
          isRequired
          validationBehavior="aria"
          value={name}
          placeholder="LG Display Hải Phòng"
          onChange={setName}
        />
        <Input
          id="project-slug"
          className="uu-scope"
          label="Mã dự án"
          validationBehavior="aria"
          value={slug}
          placeholder="lg-display-hai-phong"
          onChange={setSlug}
        />
        <Input
          id="project-aliases"
          className="uu-scope"
          label="Tên gọi khác"
          validationBehavior="aria"
          value={aliases}
          placeholder="LG, LGD (không bắt buộc)"
          onChange={setAliases}
        />
        <Input
          id="project-roles"
          className="uu-scope"
          label="Vị trí tuyển dụng"
          validationBehavior="aria"
          value={roles}
          placeholder="Công nhân sản xuất, Kiểm tra"
          onChange={setRoles}
        />
        <p className="text-helper text-muted-foreground">
          Mỗi vị trí là một dòng trong danh mục «Vị trí tuyển dụng». Có vị trí
          tuyển dụng thì Agent mới tư vấn được. Số lượng tuyển không giới hạn
          nên không cần khai báo.
        </p>

        <hr className="border-border" />

        <ProjectBriefImport
          brief={brief}
          filename={briefFilename}
          busy={creatingDraft || ingesting}
          onImported={(parsed, filename, file) =>
            void onImported(parsed, filename, file)
          }
        />

        {brief ? <CarriedSummary brief={brief} /> : null}

        {state.phase === "running" ? (
          <>
            <p role="status" className="text-helper text-foreground">
              Đang nạp «{PROJECT_KNOWLEDGE_CATEGORY_LABELS[state.current]}» (
              {state.activated.length + 1}/{state.total})…
            </p>
            <IngestProgressBoard items={state.items} slow={state.slow} />
          </>
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
        {uploadError ? (
          <p role="alert" className="text-helper text-destructive">
            Tệp phiếu chưa được lưu vào tài liệu dự án: {uploadError}. Nội dung
            danh mục vẫn đã được nạp.
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
        <Button type="submit" isDisabled={!canSave}>
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
                <p className="text-caption font-semibold uppercase tracking-[0.06em] text-muted-foreground">
                  Dự án
                </p>
                <h1 className="mt-1 text-content-title font-semibold">
                  Tạo dự án
                </h1>
              </div>
              <Button
                type="button"
                color="secondary"
                size="sm"
                iconLeading={X}
                onClick={() => redirect("/projects")}
                aria-label="Đóng và quay lại danh sách dự án"
              >
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
