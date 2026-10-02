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
  buildJobsMarkdown,
  planBriefKnowledge,
} from "./domain/project-knowledge-markdown";
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
 *  the category markdown the pipeline writes, not through this form. The highlights
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
  const [sourceReady, setSourceReady] = useState(false);

  // The slug is derived, never typed: a hand-typed one contradicts the name it
  // is supposed to identify, and the brief's own slug loses to the name the
  // recruiter actually typed above it.
  useEffect(() => {
    if (!draftId && name.trim()) setSlug(slugifyVietnamese(name));
  }, [name, draftId]);

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
    setSourceReady(false);
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
        setSlug(
          String(
            created.data.slug ??
              slugifyVietnamese(name.trim() || parsed.name || "du-an-moi"),
          ),
        );
      }
      setIngestedRoles(parsed.roles.join(", "));
      const result = await ingest(id, planBriefKnowledge(parsed).writes, file);
      // Only confirmed source content can become recruiting claims. A failed
      // upload must not leave highlights that a later retry could publish.
      if (
        result.ok &&
        !result.requiresCutover &&
        parsed.highlights.length > 0
      ) {
        await updateProjectDiscoveryCard(id, {
          discovery_card: { highlights: parsed.highlights },
        });
      }
      setSourceReady(result.ok && !result.requiresCutover);
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
    if (!draftId || !name.trim() || !sourceReady) return;
    if (state.phase === "done" && state.requiresCutover) return;
    const roleList = parseCommaList(roles);
    setSubmitting(true);
    try {
      // An edited role list is a real change to the knowledge, so it is written
      // before the project is allowed to go live — otherwise the live project
      // would answer with roles the recruiter just removed.
      if (rolesDirty) {
        const result = await ingest(draftId, [
          {
            key: "jobs",
            filename: "jobs.md",
            content: buildJobsMarkdown(roleList, brief?.location),
          },
        ]);
        if (!result.ok || result.requiresCutover) return;
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
      notify("Đã tạo dự án. Kiến thức đã sẵn sàng cho chatbot.", {
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
    draftId !== null &&
    Boolean(name.trim()) &&
    sourceReady &&
    !(state.phase === "done" && state.requiresCutover) &&
    !ingesting &&
    !creatingDraft &&
    !submitting;
  const ingestBlocked = state.phase === "failed";

  return (
    <Form onSubmit={onSubmit}>
      <div className="project-create-form">
        <section
          className="project-create-section"
          aria-labelledby="project-create-source-title"
        >
          <div className="project-section-heading">
            <span className="project-step-number" aria-hidden="true">
              1
            </span>
            <div>
              <h2
                id="project-create-source-title"
                className="text-section-title font-semibold"
              >
                Nạp kiến thức
              </h2>
              <p className="text-helper text-muted-foreground">
                Chọn một tệp thông tin dự án để hệ thống phân loại nội dung.
              </p>
            </div>
          </div>
          <ProjectBriefImport
            brief={brief}
            filename={briefFilename}
            busy={creatingDraft || ingesting}
            onImported={(parsed, filename, file) =>
              void onImported(parsed, filename, file)
            }
          />
          {brief ? <CarriedSummary brief={brief} /> : null}
        </section>

        <section
          className="project-create-section"
          aria-labelledby="project-create-info-title"
        >
          <div className="project-section-heading">
            <span className="project-step-number" aria-hidden="true">
              2
            </span>
            <div>
              <h2
                id="project-create-info-title"
                className="text-section-title font-semibold"
              >
                Kiểm tra thông tin
              </h2>
              <p className="text-helper text-muted-foreground">
                Thông tin từ tệp được điền sẵn. Bạn có thể chỉnh sửa trước khi
                tạo.
              </p>
            </div>
          </div>
          <div className="project-create-fields">
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
              hint={
                draftId ? "Mã cố định của bản nháp." : "Tự tạo từ tên dự án."
              }
              validationBehavior="aria"
              value={slug}
              isReadOnly
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
          </div>
          <p className="text-helper text-muted-foreground">
            Các vị trí cách nhau bằng dấu phẩy. Bạn có thể bổ sung sau.
          </p>
        </section>

        <div className="project-create-feedback">
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
              {state.requiresCutover
                ? `Đã chuẩn bị và kiểm tra ${state.activated.length} phần kiến thức. Cần hoàn tất bước chuyển sang 12 danh mục trước khi Chatbot sử dụng dữ liệu mới.`
                : `Đã nạp xong ${state.activated.length} phần kiến thức. Bạn có thể kiểm tra rồi tạo dự án.`}
            </p>
          ) : null}
          {ingestBlocked ? (
            <p role="alert" className="text-helper text-destructive">
              Chưa xác nhận hoàn tất «
              {PROJECT_KNOWLEDGE_CATEGORY_LABELS[state.failed]}»
              {state.message ? `: ${state.message}` : "."} Dự án vẫn là bản nháp
              và chưa hiển thị với ứng viên. Kiểm tra trạng thái trong bản nháp;
              nếu hệ thống báo lỗi nội dung, chỉnh sửa rồi nạp lại.
            </p>
          ) : null}
          {ingestBlocked && draftId ? (
            <Button
              color="secondary"
              className="uu-scope w-fit"
              onClick={() => redirect("edit", "projects", draftId)}
            >
              Kiểm tra bản nháp
            </Button>
          ) : null}
          {rolesDirty && draftId ? (
            <p className="text-helper text-muted-foreground">
              Danh sách vị trí đã sửa — sẽ được nạp lại khi bạn bấm «Tạo dự án».
              {sourceReady && ingestBlocked
                ? " Bạn có thể bấm lại để thử nạp các vị trí đã sửa."
                : ""}
            </p>
          ) : null}
        </div>
        <footer className="project-form-footer">
          <p className="text-helper text-muted-foreground">
            Dự án chỉ hiển thị với ứng viên sau khi bạn bấm «Tạo dự án».
          </p>
          <Button
            type="submit"
            className="uu-scope project-create-submit"
            isDisabled={!canSave}
            isLoading={submitting}
            showTextWhileLoading
          >
            {submitting ? "Đang tạo…" : "Tạo dự án"}
          </Button>
        </footer>
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
                <p className="project-page-description">
                  Nạp thông tin, kiểm tra nội dung và bật tuyển dụng.
                </p>
              </div>
              <Button
                type="button"
                color="secondary"
                size="sm"
                className="uu-scope"
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
