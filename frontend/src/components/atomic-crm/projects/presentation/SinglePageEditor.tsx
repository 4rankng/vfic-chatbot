import { FileText, Upload } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useId, useRef } from "react";
import type { SinglePageDraft } from "./use-single-page-draft";

type Props = {
  draft: SinglePageDraft;
  editable: boolean;
};

/** The single knowledge page an Agent reads in full. */
export const SinglePageEditor = ({ draft, editable }: Props) => {
  const {
    filename,
    hasCurrentPage,
    loadFailed,
    loading,
    readFile,
    reload,
    save,
    saving,
    setFilename,
    setText,
    text,
  } = draft;
  const filenameId = useId();
  const fileInputRef = useRef<HTMLInputElement>(null);

  return (
    <Card className="project-single-page-card">
      <CardHeader className="project-single-page-header">
        <CardTitle className="project-single-page-title text-section-title">
          <span className="project-single-page-title-label">
            <FileText className="size-5 shrink-0" aria-hidden="true" />
            <span>Trang kiến thức duy nhất</span>
          </span>
          <Badge variant="outline">Chatbot đọc toàn bộ trang</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="project-single-page-content space-y-4">
        <p className="text-body text-muted-foreground">
          Chatbot dùng toàn bộ trang này mỗi cuộc trò chuyện. Lưu sẽ thay thế
          nội dung cũ.
        </p>
        {loading ? (
          <Skeleton className="h-72 w-full" />
        ) : (
          <>
            {loadFailed ? (
              <div
                role="alert"
                className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/25 bg-destructive/5 p-3 text-body"
              >
                <p>
                  Chưa tải được nội dung hiện tại. Thử lại trước khi chỉnh sửa.
                </p>
                <Button variant="outline" onClick={() => void reload()}>
                  Thử lại
                </Button>
              </div>
            ) : null}
            <div className="project-single-page-file-row">
              <div className="min-w-0 space-y-1.5">
                <label htmlFor={filenameId} className="text-label font-medium">
                  Tên tệp kiến thức
                </label>
                <Input
                  id={filenameId}
                  value={filename}
                  onChange={(event) => setFilename(event.target.value)}
                  className="project-single-page-filename"
                  disabled={!editable || saving || loadFailed}
                  aria-label="Tên file trang kiến thức"
                />
              </div>
              {editable && (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    className="project-single-page-file-button"
                    disabled={saving || loadFailed}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <Upload className="size-4" aria-hidden="true" />
                    Chọn file
                  </Button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    hidden
                    accept=".txt,.md,.docx,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    aria-label="Chọn tệp trang kiến thức"
                    disabled={saving || loadFailed}
                    onChange={(event) => {
                      void readFile(event.target.files?.[0]);
                      event.target.value = "";
                    }}
                  />
                </>
              )}
            </div>
            <Textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={18}
              readOnly={!editable || loadFailed}
              disabled={saving}
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
          </>
        )}
      </CardContent>
    </Card>
  );
};
