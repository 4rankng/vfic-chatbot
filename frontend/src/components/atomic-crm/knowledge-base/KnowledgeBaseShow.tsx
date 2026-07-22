import {
  ShowBase,
  useGetList,
  useNotify,
  useRecordContext,
  useRefresh,
} from "ra-core";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";
import { Link } from "react-router";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import type {
  KnowledgeBase,
  KnowledgeBaseProject,
  Persona,
  Project,
} from "../types";
import { ApiError, apiJson } from "../providers/rest/api";
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

const Content = () => {
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
  const [loading, setLoading] = useState(false);
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
    }
  };

  const attachProject = async (project: Project) => {
    setLoading(true);
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
      setLoading(false);
    }
  };

  return (
    <PageShell>
      <PageHeading
        eyebrow={kb.mode === "RAG" ? "Kho kiến thức RAG" : "Ngữ cảnh trực tiếp"}
        title={kb.name}
        subtitle={
          kb.mode === "RAG"
            ? "Nhiều dự án, nhà máy, vị trí và pipeline trong một kho dùng chung."
            : "Một tệp văn bản được gửi nguyên vẹn cho mỗi lượt xử lý."
        }
        actions={
          <Button asChild variant="outline" size="sm">
            <Link to="/knowledge_bases">
              <ArrowLeft className="size-4" aria-hidden="true" />
              Quay lại
            </Link>
          </Button>
        }
      />
      <div className="mt-4 grid gap-4 sm:mt-0 lg:grid-cols-2">
        <Card className="border-[var(--tt-border)] shadow-[var(--tt-shadow-xs)]">
          <CardHeader>
            <CardTitle>Agent được gắn</CardTitle>
          </CardHeader>
          <CardContent>
            {attached.length ? (
              <ul className="space-y-2">
                {attached.map((persona) => (
                  <li key={persona.id}>{persona.name}</li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground">Chưa có Agent.</p>
            )}
          </CardContent>
        </Card>

        {kb.mode === "RAG" ? (
          <Card className="border-[var(--tt-border)] shadow-[var(--tt-shadow-xs)]">
            <CardHeader>
              <CardTitle>Dự án trong Knowledge Base</CardTitle>
            </CardHeader>
            <CardContent>
              {projects.length ? (
                <ul className="space-y-4">
                  {projects.map((project) => (
                    <li
                      key={project.id}
                      className="border-b pb-3 last:border-0 last:pb-0"
                    >
                      <p className="font-medium">{project.name}</p>
                      <p className="text-body-sm text-muted-foreground">
                        {project.knowledge_document_count} tệp ·{" "}
                        {project.active_job_count} vị trí đang tuyển
                      </p>
                      {project.factories.length > 0 && (
                        <p className="mt-1 text-body-sm text-muted-foreground">
                          Nhà máy:{" "}
                          {project.factories
                            .map((factory) =>
                              [factory.name, ...factory.aliases].join(" · "),
                            )
                            .join("; ")}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground">Chưa có dự án được gắn.</p>
              )}
            </CardContent>
          </Card>
        ) : (
          <Card className="border-[var(--tt-border)] shadow-[var(--tt-shadow-xs)]">
            <CardHeader>
              <CardTitle>Tệp ngữ cảnh trực tiếp</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {capacity && (
                <p
                  className={
                    capacity.fits ? "text-muted-foreground" : "text-destructive"
                  }
                >
                  {capacity.fits
                    ? `Phù hợp ${capacity.model}: ${capacity.estimated_input_tokens}/${capacity.available_input_tokens} token`
                    : "Tệp vượt giới hạn ngữ cảnh của model đang dùng."}
                </p>
              )}
              {loadFailed && (
                <p className="text-destructive">
                  Chưa tải được trạng thái Knowledge Base. Vui lòng tải lại
                  trang.
                </p>
              )}
              <Textarea
                value={text}
                onChange={(event) => setText(event.target.value)}
                rows={14}
                placeholder="Nhập nội dung .txt hoặc .md"
              />
              <Button
                onClick={saveDirectFile}
                disabled={knowledgeLoading || loadFailed || !text.trim()}
              >
                Lưu tệp duy nhất
              </Button>
            </CardContent>
          </Card>
        )}

        {kb.mode === "RAG" && (
          <Card className="border-[var(--tt-border)] shadow-[var(--tt-shadow-xs)]">
            <CardHeader>
              <CardTitle>Gắn dự án có sẵn</CardTitle>
            </CardHeader>
            <CardContent>
              {attachableProjects.length ? (
                <ul className="space-y-3">
                  {attachableProjects.map((project) => (
                    <li
                      key={project.id}
                      className="flex items-center justify-between gap-3"
                    >
                      <span>{project.name}</span>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={loading}
                        onClick={() => void attachProject(project)}
                      >
                        Gắn vào KB
                      </Button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground">
                  Không có dự án chưa gắn. Tạo dự án mới từ màn hình Dự án.
                </p>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </PageShell>
  );
};

export const KnowledgeBaseShow = () => (
  <ShowBase resource="knowledge_bases">
    <Content />
  </ShowBase>
);
