import {
  ShowBase,
  useGetList,
  useNotify,
  useRecordContext,
  useRefresh,
} from "ra-core";
import { type ReactNode, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft, LoaderCircle } from "lucide-react";
import { Link } from "react-router";
import { Textarea } from "@/components/ui/textarea";
import type {
  KnowledgeBase,
  KnowledgeBaseProject,
  Persona,
  Project,
} from "../types";
import { ApiError, apiJson } from "@/lib/apiClient";
import { PageHeading, PageShell } from "../kit";

type DirectFile = {
  filename: string;
  text: string;
  char_count: number;
  line_count: number;
};

type Capacity = {
  model: string;
  available_input_tokens: number;
  estimated_input_tokens: number;
  fits: boolean;
};

const Fact = ({ label, value }: { label: string; value: ReactNode }) => (
  <div className="min-w-0 border-b border-[var(--tt-border)] px-4 py-3 sm:odd:border-r">
    <dt className="text-caption uppercase tracking-wide text-muted-foreground">
      {label}
    </dt>
    <dd className="mt-1 break-words text-body font-semibold text-foreground">
      {value}
    </dd>
  </div>
);

const KnowledgeSection = ({
  id,
  title,
  count,
  children,
  className,
}: {
  id: string;
  title: string;
  count?: number;
  children: ReactNode;
  className?: string;
}) => (
  <section
    className={`min-w-0 border-t border-[var(--tt-border)] ${className ?? ""}`}
    aria-labelledby={id}
  >
    <header className="flex min-h-14 items-center justify-between gap-3 px-4 py-3">
      <h2 id={id} className="text-section-title font-semibold text-foreground">
        {title}
      </h2>
      {count !== undefined ? (
        <span
          className="text-helper tabular-nums text-muted-foreground"
          aria-label={`${count} mục`}
        >
          {count}
        </span>
      ) : null}
    </header>
    <div className="border-t border-[var(--tt-border)] px-4 py-3">
      {children}
    </div>
  </section>
);

export const KnowledgeBaseShowContent = () => {
  const kb = useRecordContext<KnowledgeBase>();
  const notify = useNotify();
  const refresh = useRefresh();
  const { data: personas = [] } = useGetList<Persona>("personas", {
    pagination: { page: 1, perPage: 100 },
    sort: { field: "name", order: "ASC" },
    filter: {},
  });
  const { data: allProjects = [] } = useGetList<Project>("projects", {
    pagination: { page: 1, perPage: 100 },
    sort: { field: "name", order: "ASC" },
    filter: {},
  });
  const [projects, setProjects] = useState<KnowledgeBaseProject[]>([]);
  const [file, setFile] = useState<DirectFile | null>(null);
  const [capacity, setCapacity] = useState<Capacity | null>(null);
  const [text, setText] = useState("");
  const [attachingProjectId, setAttachingProjectId] = useState<string | null>(
    null,
  );
  const [savingFile, setSavingFile] = useState(false);
  const [knowledgeLoading, setKnowledgeLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!kb) return;
    let active = true;
    setProjects([]);
    setFile(null);
    setCapacity(null);
    setText("");
    setKnowledgeLoading(true);
    setLoadFailed(false);

    const load = async () => {
      try {
        if (kb.mode === "RAG") {
          const value = await apiJson<KnowledgeBaseProject[]>(
            `/api/v1/knowledge-bases/${kb.id}/projects`,
          );
          if (active) setProjects(value);
          return;
        }
        const [ownedProjects, directFile, directCapacity] = await Promise.all([
          apiJson<KnowledgeBaseProject[]>(
            `/api/v1/knowledge-bases/${kb.id}/projects`,
          ),
          apiJson<DirectFile>(
            `/api/v1/knowledge-bases/${kb.id}/direct-file`,
          ).catch((error: unknown) => {
            if (error instanceof ApiError && error.status === 409) return null;
            throw error;
          }),
          apiJson<Capacity>(
            `/api/v1/knowledge-bases/${kb.id}/direct-context-capacity`,
          ).catch(() => null),
        ]);
        if (!active) return;
        setProjects(ownedProjects);
        setFile(directFile);
        setText(directFile?.text ?? "");
        setCapacity(directCapacity);
      } catch (error) {
        if (active) {
          setLoadFailed(true);
          notify((error as Error).message, { type: "error" });
        }
      } finally {
        if (active) setKnowledgeLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [kb?.id, kb?.mode, notify, reloadKey]);

  if (!kb) return null;

  const attached = personas.filter(
    (persona) => persona.knowledge_base_id === kb.id,
  );
  const attachableProjects = allProjects.filter(
    (project) => !project.knowledge_base_id,
  );

  const saveDirectFile = async () => {
    if (loadFailed) {
      notify(
        "Chưa tải được trạng thái Knowledge Base. Vui lòng tải lại trước khi lưu.",
        {
          type: "warning",
        },
      );
      return;
    }
    const owningProject = projects[0];
    if (
      file &&
      owningProject &&
      !owningProject.is_active &&
      !window.confirm("Lưu tệp mới sẽ bật dự án để Agent sử dụng. Tiếp tục?")
    ) {
      return;
    }
    setSavingFile(true);
    try {
      await apiJson(`/api/v1/knowledge-bases/${kb.id}/direct-file`, {
        method: "PUT",
        body: { filename: file?.filename ?? "knowledge.md", text },
      });
      notify(
        owningProject && !owningProject.is_active
          ? "Đã lưu tệp ngữ cảnh và bật dự án."
          : "Đã lưu tệp ngữ cảnh trực tiếp.",
        { type: "success" },
      );
      setReloadKey((value) => value + 1);
      refresh();
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setSavingFile(false);
    }
  };

  const attachProject = async (project: Project) => {
    setAttachingProjectId(String(project.id));
    try {
      await apiJson(`/api/v1/knowledge-bases/${kb.id}/projects/${project.id}`, {
        method: "POST",
      });
      notify(`Đã gắn dự án ${project.name}.`, { type: "success" });
      setReloadKey((value) => value + 1);
      refresh();
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setAttachingProjectId(null);
    }
  };

  const modeLabel = kb.mode === "RAG" ? "RAG" : "Trực tiếp";

  return (
    <PageShell>
      <PageHeading
        eyebrow={kb.mode === "RAG" ? "Kho kiến thức RAG" : "Ngữ cảnh trực tiếp"}
        title={kb.name}
        subtitle={
          kb.mode === "RAG"
            ? "Dùng chung cho nhiều dự án và Agent."
            : "Một tệp được gửi nguyên vẹn theo lượt."
        }
        actions={
          <Button asChild variant="outline" size="sm">
            <Link to="/knowledge_bases">
              <ArrowLeft className="size-4" aria-hidden="true" />
              Kho kiến thức
            </Link>
          </Button>
        }
      />

      <dl className="mt-4 grid border-y border-[var(--tt-border)] sm:grid-cols-3">
        <Fact label="Chế độ" value={modeLabel} />
        <Fact label="Agent" value={attached.length} />
        <Fact
          label="Dự án"
          value={knowledgeLoading || loadFailed ? "—" : projects.length}
        />
      </dl>

      {loadFailed ? (
        <div
          role="alert"
          className="mt-4 flex flex-wrap items-center justify-between gap-3 border-y border-destructive/30 px-4 py-3 text-body text-destructive"
        >
          <span>Chưa tải được dữ liệu kho.</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setReloadKey((value) => value + 1)}
          >
            Thử lại
          </Button>
        </div>
      ) : null}

      <div className="mt-6 grid gap-x-8 gap-y-6 lg:grid-cols-2">
        <KnowledgeSection
          id="knowledge-base-agents-title"
          title="Agent được gắn"
          count={attached.length}
        >
          {attached.length ? (
            <ul className="divide-y divide-[var(--tt-border)]">
              {attached.map((persona) => (
                <li key={persona.id} className="py-2.5 first:pt-0 last:pb-0">
                  {persona.name}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-body text-muted-foreground">Chưa có Agent.</p>
          )}
        </KnowledgeSection>

        {kb.mode === "RAG" ? (
          <KnowledgeSection
            id="knowledge-base-projects-title"
            title="Dự án"
            count={
              knowledgeLoading || loadFailed ? undefined : projects.length
            }
          >
            {knowledgeLoading ? (
              <p role="status" className="text-body text-muted-foreground">
                Đang tải dự án…
              </p>
            ) : loadFailed ? (
              <p className="text-body text-muted-foreground">
                Dữ liệu chưa sẵn sàng.
              </p>
            ) : projects.length ? (
              <ul className="divide-y divide-[var(--tt-border)]">
                {projects.map((project) => (
                  <li key={project.id} className="py-3 first:pt-0 last:pb-0">
                    <p className="font-medium text-foreground">
                      {project.name}
                    </p>
                    <p className="mt-1 text-helper text-muted-foreground">
                      {project.knowledge_document_count} tệp ·{" "}
                      {project.active_job_count} vị trí đang tuyển
                    </p>
                    {project.factories.length > 0 ? (
                      <details className="mt-2">
                        <summary className="flex min-h-11 cursor-pointer items-center text-helper font-medium text-foreground">
                          {project.factories.length} nhà máy
                        </summary>
                        <ul className="space-y-2 border-l border-[var(--tt-border)] pl-3 text-helper text-muted-foreground">
                          {project.factories.map((factory) => (
                            <li key={factory.name}>
                              <span className="font-medium text-foreground">
                                {factory.name}
                              </span>
                              {factory.aliases.length
                                ? ` · ${factory.aliases.join(" · ")}`
                                : ""}
                            </li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-body text-muted-foreground">
                Chưa có dự án được gắn.
              </p>
            )}
          </KnowledgeSection>
        ) : (
          <KnowledgeSection
            id="knowledge-base-direct-file-title"
            title="Tệp ngữ cảnh"
          >
            <div className="space-y-3">
              {knowledgeLoading ? (
                <p role="status" className="text-body text-muted-foreground">
                  Đang tải tệp…
                </p>
              ) : null}
              {capacity ? (
                <p
                  className={
                    capacity.fits
                      ? "text-helper text-muted-foreground"
                      : "text-helper text-destructive"
                  }
                >
                  {capacity.fits
                    ? `${capacity.estimated_input_tokens}/${capacity.available_input_tokens} token · ${capacity.model}`
                    : "Tệp vượt giới hạn ngữ cảnh của model."}
                </p>
              ) : null}
              <Textarea
                value={text}
                onChange={(event) => setText(event.target.value)}
                rows={14}
                aria-label="Nội dung tệp ngữ cảnh"
                placeholder="Nhập nội dung .txt hoặc .md"
                disabled={knowledgeLoading || loadFailed || savingFile}
              />
              <Button
                onClick={saveDirectFile}
                disabled={
                  knowledgeLoading || loadFailed || savingFile || !text.trim()
                }
              >
                {savingFile ? (
                  <LoaderCircle
                    className="size-4 animate-spin motion-reduce:animate-none"
                    aria-hidden="true"
                  />
                ) : null}
                {savingFile ? "Đang lưu…" : "Lưu tệp"}
              </Button>
            </div>
          </KnowledgeSection>
        )}

        {kb.mode === "RAG" ? (
          <KnowledgeSection
            id="knowledge-base-attach-project-title"
            title="Gắn dự án"
            className="lg:col-span-2"
          >
            {knowledgeLoading ? (
              <p role="status" className="text-body text-muted-foreground">
                Đang kiểm tra dự án…
              </p>
            ) : loadFailed ? (
              <p className="text-body text-muted-foreground">
                Dữ liệu chưa sẵn sàng.
              </p>
            ) : attachableProjects.length ? (
              <ul className="divide-y divide-[var(--tt-border)]">
                {attachableProjects.map((project) => {
                  const isAttaching = attachingProjectId === String(project.id);
                  return (
                    <li
                      key={project.id}
                      className="flex min-h-14 items-center justify-between gap-3 py-2"
                    >
                      <span className="min-w-0 truncate">{project.name}</span>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={attachingProjectId !== null}
                        onClick={() => void attachProject(project)}
                      >
                        {isAttaching ? (
                          <LoaderCircle
                            className="size-4 animate-spin motion-reduce:animate-none"
                            aria-hidden="true"
                          />
                        ) : null}
                        {isAttaching ? "Đang gắn…" : "Gắn"}
                      </Button>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-body text-muted-foreground">
                  Không còn dự án chưa gắn.
                </p>
                <Button asChild variant="outline" size="sm">
                  <Link to="/projects/create">Tạo dự án</Link>
                </Button>
              </div>
            )}
          </KnowledgeSection>
        ) : null}
      </div>
    </PageShell>
  );
};

export const KnowledgeBaseShow = () => (
  <ShowBase resource="knowledge_bases">
    <KnowledgeBaseShowContent />
  </ShowBase>
);
