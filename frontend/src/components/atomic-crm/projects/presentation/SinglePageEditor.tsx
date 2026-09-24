import {
  AlertCircle,
  ArrowRight,
  ChevronDown,
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
import type { SinglePageDraft } from "./use-single-page-draft";
import { ExternalSourceLinkForm } from "../ExternalSourceLinkForm";
import { ExternalSourceList } from "../ExternalSourceList";

type Props = {
  projectId: string;
  draft: SinglePageDraft;
  editable: boolean;
};

/** The single knowledge page an Agent reads in full, plus its Sheet sync. */
export const SinglePageEditor = ({ projectId, draft, editable }: Props) => {
  const {
    autoSyncOn,
    filename,
    handleSourceChange,
    handleSynchronized,
    hasCurrentPage,
    loadFailed,
    loading,
    readFile,
    refreshing,
    save,
    saving,
    setFilename,
    setText,
    syncRefreshKey,
    text,
  } = draft;

  return (
    <Card className="project-single-page-card">
      <CardHeader className="project-single-page-header">
        <CardTitle className="project-single-page-title text-section-title">
          <span className="project-single-page-title-label">
            <FileText className="size-5 shrink-0" aria-hidden="true" />
            <span>Trang kiến thức duy nhất</span>
          </span>
          <Badge variant="outline">Gửi toàn bộ cho Agent</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="project-single-page-content space-y-4">
        <p className="text-body text-muted-foreground">
          Agent dùng toàn bộ trang này mỗi cuộc trò chuyện. Lưu sẽ thay thế nội
          dung cũ.
        </p>
        {loading ? (
          <Skeleton className="h-72 w-full" />
        ) : (
          <>
            <div className="project-single-page-file-row">
              <Input
                value={filename}
                onChange={(event) => setFilename(event.target.value)}
                className="project-single-page-filename"
                disabled={!editable}
                aria-label="Tên file trang kiến thức"
              />
              {editable && (
                <Button
                  variant="outline"
                  className="project-single-page-file-button"
                  asChild
                >
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
              className="project-single-page-textarea font-mono text-body"
            />
            {editable && (
              <Button
                className="project-single-page-save"
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
                <header className="project-single-page-sync-header flex flex-wrap items-center gap-x-2 gap-y-1 text-label font-semibold">
                  <div className="inline-flex min-w-0 items-center gap-2 whitespace-nowrap">
                    <Link2
                      className="size-4 shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                    <h3
                      id="single-page-sync-heading"
                      className="flex min-w-0 items-center gap-1.5"
                    >
                      <span>Google Sheet</span>
                      <ArrowRight
                        className="size-3.5 shrink-0 text-muted-foreground"
                        aria-hidden="true"
                      />
                      <span>Trang kiến thức</span>
                    </h3>
                  </div>
                  {refreshing && (
                    <span
                      className="text-body-sm font-normal text-muted-foreground"
                      aria-live="polite"
                    >
                      · Đang nạp nội dung mới nhất…
                    </span>
                  )}
                </header>

                <div className="space-y-3">
                  {autoSyncOn && (
                    <details className="group rounded-md border border-warning/30 bg-warning/10 text-foreground">
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
                        Khi lịch hàng ngày đang bật, dữ liệu mới từ Google Sheet
                        sẽ thay thế nội dung sửa thủ công ở lần đồng bộ tiếp
                        theo.
                      </div>
                    </details>
                  )}
                  <ExternalSourceLinkForm
                    projectId={projectId}
                    variant="single-page"
                    onCreated={handleSourceChange}
                  />
                  <ExternalSourceList
                    projectId={projectId}
                    variant="single-page"
                    refreshSignal={syncRefreshKey}
                    onChange={handleSourceChange}
                    onSynchronized={handleSynchronized}
                  />
                </div>
              </section>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
};
