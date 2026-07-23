import { useCallback, useEffect, useRef, useState } from "react";
import { useDataProvider, useNotify, useRefresh } from "ra-core";
import { ApiError } from "@/components/atomic-crm/providers/rest/api";
import {
  AlertCircle,
  ArrowRight,
  ChevronDown,
  Database,
  Download,
  FileText,
  Link2,
  Upload,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { Project } from "../types";
import { BusTimetableSection } from "./ProjectBusTimetable";
import {
  getProjectKnowledgeCategories,
  getProjectKnowledgeCategorySource,
  getProjectKnowledgeCategoryTemplate,
  getProjectSinglePage,
  listSinglePageExternalSources,
  listExternalSources,
  replaceProjectSinglePage,
  uploadProjectKnowledgeCategory,
  type KnowledgeCategoryKey,
  type KnowledgeCategoryStatus,
} from "@/lib/vfic/knowledgeService";
import { cn } from "@/lib/utils";
import { ExternalSourceLinkForm } from "./ExternalSourceLinkForm";
import { ExternalSourceList } from "./ExternalSourceList";

type Props = {
  project: Project;
  editable?: boolean;
};

export const ProjectKnowledgePanel = ({ project, editable = false }: Props) => {
  if (project.knowledge_mode === "DIRECT_CONTEXT") {
    return <SinglePagePanel project={project} editable={editable} />;
  }
  return <RagCategoriesPanel project={project} editable={editable} />;
};

const SinglePagePanel = ({ project, editable }: Props) => {
  const notify = useNotify();
  const refresh = useRefresh();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [filename, setFilename] = useState("single-page.md");
  const [text, setText] = useState("");
  const [hasCurrentPage, setHasCurrentPage] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [refreshingPage, setRefreshingPage] = useState(false);
  const [singlePageSyncRefreshKey, setSinglePageSyncRefreshKey] = useState(0);
  const [singlePageAutoSyncOn, setSinglePageAutoSyncOn] = useState(false);
  const loadRequestRef = useRef(0);

  const loadPage = useCallback(
    async ({ background = false }: { background?: boolean } = {}) => {
      const requestId = ++loadRequestRef.current;
      if (background) {
        setRefreshingPage(true);
      } else {
        setLoading(true);
      }
      try {
        const page = await getProjectSinglePage(String(project.id));
        if (requestId !== loadRequestRef.current) return;
        setFilename(page.filename);
        setText(page.text);
        setHasCurrentPage(true);
        setLoadFailed(false);
      } catch (error: unknown) {
        if (requestId !== loadRequestRef.current) return;
        if (error instanceof ApiError && error.status === 404) {
          setFilename("single-page.md");
          setText("");
          setHasCurrentPage(false);
          setLoadFailed(false);
          return;
        }
        setLoadFailed(true);
        notify((error as Error).message, { type: "error" });
      } finally {
        if (requestId === loadRequestRef.current) {
          if (background) {
            setRefreshingPage(false);
          } else {
            setLoading(false);
          }
        }
      }
    },
    [notify, project.id],
  );

  const loadSinglePageSyncState = useCallback(async () => {
    if (!editable) return;
    try {
      const rows = await listSinglePageExternalSources(String(project.id));
      setSinglePageAutoSyncOn(rows.some((row) => row.auto_sync_enabled));
    } catch {
      setSinglePageAutoSyncOn(false);
    }
  }, [editable, project.id]);

  const handleSinglePageSourceChange = useCallback(() => {
    void loadSinglePageSyncState();
    setSinglePageSyncRefreshKey((value) => value + 1);
  }, [loadSinglePageSyncState]);

  const handleSinglePageSynchronized = useCallback(() => {
    void loadPage({ background: true });
    void loadSinglePageSyncState();
  }, [loadPage, loadSinglePageSyncState]);

  useEffect(() => {
    void loadPage();
    void loadSinglePageSyncState();
    return () => {
      loadRequestRef.current += 1;
    };
  }, [loadPage, loadSinglePageSyncState]);

  const save = async () => {
    if (loadFailed) {
      notify(
        "Chưa tải được nội dung hiện tại. Vui lòng tải lại trang trước khi lưu.",
        {
          type: "warning",
        },
      );
      return;
    }
    if (!text.trim()) {
      notify("Vui lòng nhập nội dung kiến thức.", { type: "warning" });
      return;
    }
    if (
      hasCurrentPage &&
      !window.confirm(
        project.is_active
          ? "Nội dung mới sẽ thay thế toàn bộ trang hiện tại. Tiếp tục?"
          : "Nội dung mới sẽ thay thế toàn bộ trang hiện tại và bật dự án để Agent sử dụng. Tiếp tục?",
      )
    ) {
      return;
    }
    setSaving(true);
    try {
      await replaceProjectSinglePage(String(project.id), filename, text);
      setHasCurrentPage(true);
      notify(
        project.is_active
          ? "Đã thay thế trang kiến thức của dự án."
          : "Đã lưu trang kiến thức và bật dự án.",
        { type: "success" },
      );
      refresh();
      void loadSinglePageSyncState();
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  const readFile = async (file?: File) => {
    if (!file) return;
    if (!/\.(txt|md)$/i.test(file.name)) {
      notify("Trang kiến thức chỉ nhận file .txt hoặc .md.", {
        type: "warning",
      });
      return;
    }
    setFilename(file.name);
    setText(await file.text());
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-section-title">
            <FileText className="size-5" />
            Trang kiến thức duy nhất
            <Badge variant="outline">Gửi toàn bộ cho Agent</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-body text-muted-foreground">
            Agent dùng toàn bộ trang này mỗi cuộc trò chuyện. Lưu sẽ thay thế
            nội dung cũ.
          </p>
          {loading ? (
            <Skeleton className="h-72 w-full" />
          ) : (
            <>
              <div className="flex flex-wrap gap-2">
                <Input
                  value={filename}
                  onChange={(event) => setFilename(event.target.value)}
                  className="max-w-sm"
                  disabled={!editable}
                  aria-label="Tên file trang kiến thức"
                />
                {editable && (
                  <Button variant="outline" asChild>
                    <label>
                      <Upload className="size-4" />
                      Chọn file
                      <input
                        type="file"
                        accept=".txt,.md,text/plain,text/markdown"
                        className="sr-only"
                        onChange={(event) =>
                          void readFile(event.target.files?.[0])
                        }
                      />
                    </label>
                  </Button>
                )}
              </div>
              <Textarea
                value={text}
                onChange={(event) => setText(event.target.value)}
                rows={18}
                readOnly={!editable}
                placeholder="Dán toàn bộ kiến thức của dự án tại đây..."
                aria-label="Nội dung trang kiến thức"
                className="font-mono text-body"
              />
              {editable && (
                <Button
                  onClick={() => void save()}
                  disabled={saving || loadFailed}
                >
                  {saving ? (
                    <span
                      className="tt-loading tt-loading-spinner tt-loading-sm"
                      aria-hidden="true"
                    />
                  ) : null}
                  {hasCurrentPage
                    ? "Thay thế trang hiện tại"
                    : "Lưu trang kiến thức"}
                </Button>
              )}
              {editable && (
                <section
                  className="space-y-3 border-t border-border/60 pt-4"
                  aria-labelledby="single-page-sync-heading"
                >
                  <header className="flex flex-wrap items-center gap-x-2 gap-y-1 text-label font-semibold">
                    <Link2
                      className="size-4 text-muted-foreground"
                      aria-hidden="true"
                    />
                    <h3
                      id="single-page-sync-heading"
                      className="flex items-center gap-1.5"
                    >
                      <span>Google Sheet</span>
                      <ArrowRight
                        className="size-3.5 text-muted-foreground"
                        aria-hidden="true"
                      />
                      <span>Trang kiến thức</span>
                    </h3>
                    {refreshingPage && (
                      <span
                        className="text-body-sm font-normal text-muted-foreground"
                        aria-live="polite"
                      >
                        · Đang nạp nội dung mới nhất…
                      </span>
                    )}
                  </header>

                  <div className="space-y-3">
                    {singlePageAutoSyncOn && (
                      <details className="group rounded-md border border-warning/30 bg-warning/10 text-warning-foreground">
                        <summary className="flex min-h-9 cursor-pointer list-none items-center gap-2 px-3 py-1.5 text-label font-medium outline-none transition-colors hover:bg-warning/10 focus-visible:ring-3 focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
                          <AlertCircle
                            className="size-4 shrink-0 text-warning"
                            aria-hidden="true"
                          />
                          <span className="flex-1">
                            Sheet sẽ ghi đè nội dung sửa tay
                          </span>
                          <ChevronDown
                            className="size-4 shrink-0 text-muted-foreground transition-transform duration-200 group-open:rotate-180"
                            aria-hidden="true"
                          />
                        </summary>
                        <div className="border-t border-warning/20 px-9 py-2 text-body-sm text-muted-foreground">
                          Khi lịch hàng ngày đang bật, dữ liệu mới từ Google
                          Sheet sẽ thay thế nội dung sửa thủ công ở lần đồng
                          bộ tiếp theo.
                        </div>
                      </details>
                    )}
                    <ExternalSourceLinkForm
                      projectId={String(project.id)}
                      variant="single-page"
                      onCreated={handleSinglePageSourceChange}
                    />
                    <ExternalSourceList
                      projectId={String(project.id)}
                      variant="single-page"
                      refreshSignal={singlePageSyncRefreshKey}
                      onChange={handleSinglePageSourceChange}
                      onSynchronized={handleSinglePageSynchronized}
                    />
                  </div>
                </section>
              )}
            </>
          )}
        </CardContent>
      </Card>
      {editable && <DiscoveryCardEditor project={project} />}
    </div>
  );
};

const RagCategoriesPanel = ({ project, editable }: Props) => {
  const notify = useNotify();
  const [categories, setCategories] = useState<
    KnowledgeCategoryStatus[] | null
  >(null);
  const [selected, setSelected] = useState<KnowledgeCategoryKey>("jobs");
  const [editorContent, setEditorContent] = useState("");
  const [blankTemplate, setBlankTemplate] = useState("");
  const [templateFilename, setTemplateFilename] = useState("jobs.yaml");
  const [filename, setFilename] = useState("jobs.yaml");
  const [hasCurrentSource, setHasCurrentSource] = useState(false);
  const [loadingCategory, setLoadingCategory] = useState(false);
  const [saving, setSaving] = useState(false);
  const [processingKey, setProcessingKey] =
    useState<KnowledgeCategoryKey | null>(null);
  const pollRef = useRef<number | null>(null);
  const [faqAutoSyncOn, setFaqAutoSyncOn] = useState(false);
  const [extSrcRefreshKey, setExtSrcRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    listExternalSources(String(project.id))
      .then((rows) => {
        if (!active) return;
        setFaqAutoSyncOn(
          rows.some(
            (row) => row.category_key === "faq" && row.auto_sync_enabled,
          ),
        );
      })
      .catch(() => {
        /* external-source list is optional; never block the panel */
      });
    return () => {
      active = false;
    };
  }, [project.id, extSrcRefreshKey]);

  const loadCatalog = async () => {
    const catalog = await getProjectKnowledgeCategories(String(project.id));
    setCategories(catalog.data);
    return catalog.data;
  };

  useEffect(() => {
    void loadCatalog().catch((error) =>
      notify((error as Error).message, { type: "error" }),
    );
    return () => {
      if (pollRef.current !== null) window.clearTimeout(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id]);

  useEffect(() => {
    let active = true;
    setLoadingCategory(true);
    setEditorContent("");
    setBlankTemplate("");
    setFilename(`${selected}.yaml`);
    setHasCurrentSource(false);

    void Promise.allSettled([
      getProjectKnowledgeCategorySource(String(project.id), selected),
      getProjectKnowledgeCategoryTemplate(String(project.id), selected),
    ]).then(([sourceResult, templateResult]) => {
      if (!active) return;

      if (sourceResult.status === "fulfilled") {
        setEditorContent(sourceResult.value.content);
        setFilename(sourceResult.value.filename);
        setHasCurrentSource(true);
      } else if (
        !(sourceResult.reason instanceof ApiError) ||
        sourceResult.reason.status !== 404
      ) {
        notify((sourceResult.reason as Error).message, { type: "error" });
      }

      if (templateResult.status === "fulfilled") {
        setBlankTemplate(templateResult.value.content);
        setTemplateFilename(templateResult.value.filename);
        if (sourceResult.status !== "fulfilled") {
          setFilename(templateResult.value.filename);
        }
      } else {
        notify((templateResult.reason as Error).message, { type: "error" });
      }

      setLoadingCategory(false);
    });

    return () => {
      active = false;
    };
  }, [notify, project.id, selected]);

  const pollUntilActive = (revisionId: string, attempts = 0) => {
    pollRef.current = window.setTimeout(() => {
      void loadCatalog()
        .then((rows) => {
          if (rows.some((row) => row.active_revision_id === revisionId)) {
            setProcessingKey(null);
            notify("Dữ liệu mới đã sẵn sàng cho Agent.", { type: "success" });
          } else if (
            rows.some(
              (row) =>
                row.latest_revision_id === revisionId &&
                row.status === "FAILED",
            )
          ) {
            setProcessingKey(null);
            notify("Nội dung mới có lỗi. Dữ liệu đang dùng không thay đổi.", {
              type: "error",
            });
          } else if (attempts < 20) {
            pollUntilActive(revisionId, attempts + 1);
          } else {
            setProcessingKey(null);
            notify(
              "Dữ liệu đang được xử lý. Bạn có thể quay lại kiểm tra sau.",
              {
                type: "info",
              },
            );
          }
        })
        .catch(() => setProcessingKey(null));
    }, 2000);
  };

  const upload = async (file?: File) => {
    if (!file) return;
    const content = await file.text();
    if (
      !window.confirm(
        "File này sẽ thay thế toàn bộ dữ liệu của mục đang chọn. Tiếp tục?",
      )
    ) {
      return;
    }
    setFilename(file.name);
    setEditorContent(content);
    setSaving(true);
    try {
      const result = await uploadProjectKnowledgeCategory(
        String(project.id),
        selected,
        file,
      );
      setProcessingKey(selected);
      notify("Đã tải file. Hệ thống đang kiểm tra và chuẩn bị cho Agent.", {
        type: "info",
      });
      pollUntilActive(result.revision.id);
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  const downloadTemplate = () => {
    const url = URL.createObjectURL(
      new Blob([blankTemplate], { type: "application/yaml" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = templateFilename;
    link.click();
    URL.revokeObjectURL(url);
  };

  const selectedCategory = categories?.find((item) => item.key === selected);

  const activeCategoryCount =
    categories?.filter((item) => item.active_revision_id).length ?? 0;

  return (
    <section
      className="project-knowledge-panel"
      aria-labelledby="project-knowledge-title"
    >
      <header className="project-knowledge-header">
        <h2 id="project-knowledge-title" className="project-knowledge-title">
          <Database className="size-5" aria-hidden="true" />
          Kiến thức theo danh mục
        </h2>
      </header>
      <div className="project-knowledge-content">
        <p className="project-knowledge-description">
          Mỗi mục cập nhật riêng. Việc làm: có trong file = đang tuyển.
        </p>
        {categories && (
          <div className="project-knowledge-progress" aria-live="polite">
            <span>Tiến độ nội dung</span>
            <strong>
              {activeCategoryCount}/{categories.length} mục đã có dữ liệu
            </strong>
          </div>
        )}
        {!categories ? (
          <div className="project-category-grid">
            {Array.from({ length: 12 }).map((_, index) => (
              <Skeleton key={index} className="h-24" />
            ))}
          </div>
        ) : (
          <div className="project-category-grid">
            {categories.map((category) => {
              const isProcessing = processingKey === category.key;
              const hasPendingRevision =
                category.status === "STAGED" ||
                category.status === "PROCESSING";
              const hasError = category.status === "FAILED";
              const isActive = Boolean(category.active_revision_id);
              return (
                <button
                  key={category.key}
                  type="button"
                  onClick={() => setSelected(category.key)}
                  aria-pressed={selected === category.key}
                  className={cn(
                    "project-category-card",
                    selected === category.key && "is-selected",
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="project-category-name">
                      {category.label_vi}
                    </span>
                    {isProcessing || hasPendingRevision ? (
                      <span
                        className="tt-loading tt-loading-spinner tt-loading-sm text-primary"
                        aria-hidden="true"
                      />
                    ) : hasError ? (
                      <AlertCircle
                        className="size-4 text-destructive"
                        aria-hidden="true"
                      />
                    ) : isActive ? (
                      <Badge
                        variant="secondary"
                        className="h-6 px-1.5 text-badge font-semibold"
                      >
                        v{category.active_revision_no ?? 1}
                      </Badge>
                    ) : (
                      <span
                        className="project-category-empty-dot"
                        aria-hidden="true"
                      />
                    )}
                  </div>
                  <div className="project-category-status">
                    {isProcessing || hasPendingRevision ? (
                      <span className="text-muted-foreground">Đang xử lý</span>
                    ) : hasError ? (
                      <span className="text-destructive">
                        Cập nhật lỗi — nội dung cũ vẫn đang dùng
                      </span>
                    ) : !isActive ? (
                      <span className="text-muted-foreground">
                        Chưa có dữ liệu
                      </span>
                    ) : null}
                  </div>
                  {category.updated_at && (
                    <p className="project-category-date">
                      Cập nhật {formatDate(category.updated_at)}
                    </p>
                  )}
                </button>
              );
            })}
          </div>
        )}

        <section className="project-category-editor">
          <div className="project-category-editor-header">
            <div className="project-category-editor-heading">
              <div className="project-category-editor-title-row">
                <h3 className="project-category-editor-title">
                  {selectedCategory?.label_vi ?? selected}
                </h3>
                {!loadingCategory && (
                  <Badge variant={hasCurrentSource ? "secondary" : "outline"}>
                    {hasCurrentSource
                      ? `Đang dùng v${selectedCategory?.active_revision_no ?? 1}`
                      : "Chưa có dữ liệu"}
                  </Badge>
                )}
              </div>
              <p className="project-category-editor-description">
                {hasCurrentSource
                  ? `Dữ liệu hiện tại Agent đang sử dụng · ${filename}`
                  : "Danh mục này chưa có dữ liệu đang dùng. Tải mẫu để chuẩn bị nội dung mới."}
              </p>
            </div>
            <div className="project-category-editor-actions">
              <Button
                variant="outline"
                size="sm"
                onClick={downloadTemplate}
                disabled={!blankTemplate || loadingCategory}
              >
                <Download className="size-4" /> Tải mẫu
              </Button>
              {editable && (
                <Button
                  variant="outline"
                  size="sm"
                  asChild
                  disabled={saving || loadingCategory}
                >
                  <label>
                    {saving ? (
                      <span
                        className="tt-loading tt-loading-spinner tt-loading-sm"
                        aria-hidden="true"
                      />
                    ) : (
                      <Upload className="size-4" />
                    )}
                    Tải file YAML
                    <input
                      type="file"
                      accept=".yaml,.yml,application/yaml,text/yaml"
                      className="sr-only"
                      disabled={saving || loadingCategory}
                      onChange={(event) => void upload(event.target.files?.[0])}
                    />
                  </label>
                </Button>
              )}
              {editable && (
                <ExternalSourceLinkForm
                  projectId={String(project.id)}
                  defaultCategory={selected}
                  onCreated={() => setExtSrcRefreshKey((value) => value + 1)}
                />
              )}
            </div>
          </div>
          {loadingCategory ? (
            <Skeleton className="project-category-editor-skeleton" />
          ) : (
            <Textarea
              value={editorContent}
              readOnly
              rows={20}
              className="project-category-textarea font-mono"
              aria-label={`Dữ liệu hiện tại của danh mục ${selectedCategory?.label_vi ?? selected}`}
              placeholder="Danh mục này chưa có dữ liệu. Hãy tải file YAML để thay thế."
            />
          )}
        </section>

        {selected === "faq" && faqAutoSyncOn && (
          <p
            className="rounded-md border border-amber-300 bg-amber-50 p-3 text-body-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
            role="status"
          >
            FAQ đang được đồng bộ tự động từ Google Sheet. Các thay đổi thủ công
            sẽ bị ghi đè ở lần đồng bộ tiếp theo.
          </p>
        )}

        {editable && (
          <section className="space-y-2">
            <h3 className="text-body font-semibold">
              Nguồn đồng bộ từ link công khai
            </h3>
            <ExternalSourceList
              projectId={String(project.id)}
              refreshSignal={extSrcRefreshKey}
              onChange={() => setExtSrcRefreshKey((value) => value + 1)}
            />
          </section>
        )}

        {selected === "transportation" && (
          <section className="project-transport-panel">
            <p className="project-transport-description">
              Lịch xe Agent tra cứu khi ứng viên hỏi tuyến, điểm đón, giờ đón.
            </p>
            <BusTimetableSection projectId={String(project.id)} />
          </section>
        )}
      </div>
    </section>
  );
};

const DiscoveryCardEditor = ({ project }: { project: Project }) => {
  const notify = useNotify();
  const refresh = useRefresh();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const card = project.index_card ?? {};
  const [summary, setSummary] = useState(card.summary ?? project.summary ?? "");
  const [location, setLocation] = useState(card.location ?? "");
  const [roles, setRoles] = useState(
    (card.roles ?? card.key_roles ?? []).join(", "),
  );
  const [highlights, setHighlights] = useState(
    (card.highlights ?? []).join(", "),
  );
  const [aliases, setAliases] = useState((project.aliases ?? []).join(", "));
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await dataProvider.update("projects", {
        id: project.id,
        previousData: project,
        data: {
          aliases: splitList(aliases),
          discovery_card: {
            summary: summary.trim(),
            location: location.trim(),
            roles: splitList(roles),
            eligibility: [],
            highlights: splitList(highlights),
          },
        },
      });
      notify("Đã cập nhật thẻ giúp ứng viên tìm thấy dự án.", {
        type: "success",
      });
      refresh();
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-section-title">
          Thông tin dùng khi gợi ý dự án
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2">
        <Input
          value={summary}
          onChange={(event) => setSummary(event.target.value)}
          placeholder="Tóm tắt"
        />
        <Input
          value={location}
          onChange={(event) => setLocation(event.target.value)}
          placeholder="Địa điểm"
        />
        <Input
          value={roles}
          onChange={(event) => setRoles(event.target.value)}
          placeholder="Vị trí, cách nhau bằng dấu phẩy"
        />
        <Input
          value={highlights}
          onChange={(event) => setHighlights(event.target.value)}
          placeholder="Điểm nổi bật, cách nhau bằng dấu phẩy"
        />
        <Input
          value={aliases}
          onChange={(event) => setAliases(event.target.value)}
          placeholder="Tên gọi khác: LG, LGD..."
        />
        <div>
          <Button onClick={() => void save()} disabled={saving}>
            {saving ? (
              <span
                className="tt-loading tt-loading-spinner tt-loading-sm"
                aria-hidden="true"
              />
            ) : null}
            Lưu thông tin gợi ý
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};

const splitList = (value: string) =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

const formatDate = (value: string) =>
  new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(value));
