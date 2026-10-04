import { useId, useLayoutEffect, useRef, useState } from "react";
import { Download } from "lucide-react";
import { useNotify } from "ra-core";

import { Button } from "@/components/base/buttons/button";
import { ApiError } from "@/lib/apiClient";
import {
  getProjectKnowledgeExport,
  getProjectKnowledgeFullTemplate,
} from "./project-knowledge-service";
import type { ProjectKnowledgeExport as KnowledgeFile } from "./domain/project-knowledge-contracts";

type ExportContext = { projectId: string };
type ExportRequest = { context: ExportContext; controller: AbortController };

type KnowledgeDownloadOptions = {
  projectId: string;
  getFile: (projectId: string, signal: AbortSignal) => Promise<KnowledgeFile>;
  emptyMessage: string;
  failureMessage: string;
};

/** The text download's request and browser attachment share one owner. */
export const useKnowledgeDownload = ({
  projectId,
  getFile,
  emptyMessage,
  failureMessage,
}: KnowledgeDownloadOptions) => {
  const notify = useNotify();
  const [exporting, setExporting] = useState(false);
  const contextRef = useRef<ExportContext | null>(null);
  const requestRef = useRef<ExportRequest | null>(null);

  useLayoutEffect(() => {
    const context = { projectId };
    contextRef.current = context;
    setExporting(false);
    return () => {
      if (requestRef.current?.context === context) {
        requestRef.current.controller.abort();
        requestRef.current = null;
      }
      if (contextRef.current === context) contextRef.current = null;
    };
  }, [projectId]);

  const download = async () => {
    const context = contextRef.current;
    if (!context || requestRef.current) return;
    const request = { context, controller: new AbortController() };
    requestRef.current = request;
    setExporting(true);
    try {
      const { filename, content } = await getFile(
        context.projectId,
        request.controller.signal,
      );
      if (contextRef.current !== context || request.controller.signal.aborted)
        return;
      if (!content.trim()) throw new ApiError(409, emptyMessage);
      const url = URL.createObjectURL(
        new Blob([content], { type: "text/markdown;charset=utf-8" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.hidden = true;
      try {
        document.body.appendChild(link);
        link.click();
      } finally {
        link.remove();
        // Let the browser begin consuming the attachment before releasing it.
        window.setTimeout(() => URL.revokeObjectURL(url), 0);
      }
    } catch (error) {
      if (contextRef.current === context && !request.controller.signal.aborted)
        notify(error instanceof ApiError ? error.message : failureMessage, {
          type: "error",
        });
    } finally {
      if (requestRef.current === request) {
        requestRef.current = null;
        if (contextRef.current === context) setExporting(false);
      }
    }
  };

  return { exporting, download: () => void download() };
};

/** The text download's request and browser attachment share one owner. */
const KnowledgeDownloadButton = ({
  label,
  descriptionId,
  ...options
}: KnowledgeDownloadOptions & {
  label: string;
  descriptionId?: string;
}) => {
  const { exporting, download } = useKnowledgeDownload(options);
  return (
    <Button
      className="uu-scope"
      type="button"
      color="secondary"
      size="sm"
      iconLeading={Download}
      aria-describedby={descriptionId}
      isLoading={exporting}
      isDisabled={exporting}
      showTextWhileLoading
      onClick={download}
    >
      {label}
    </Button>
  );
};

/** Downloads only the server's saved knowledge; editor drafts never enter it. */
export const ProjectKnowledgeExport = ({
  projectId,
}: {
  projectId: string;
}) => {
  const descriptionId = useId();
  return (
    <div className="uu-scope flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
      <span id={descriptionId} className="text-helper text-tertiary">
        KB đang sử dụng · Markdown (.md)
      </span>
      <KnowledgeDownloadButton
        projectId={projectId}
        getFile={getProjectKnowledgeExport}
        label="Xuất KB"
        descriptionId={descriptionId}
        emptyMessage="Dự án chưa có kiến thức đã lưu để xuất."
        failureMessage="Chưa xuất được KB. Vui lòng thử lại."
      />
    </div>
  );
};

export const ProjectKnowledgeTemplate = ({
  projectId,
}: {
  projectId: string;
}) => (
  <KnowledgeDownloadButton
    projectId={projectId}
    getFile={getProjectKnowledgeFullTemplate}
    label="Tải mẫu KB"
    emptyMessage="Mẫu KB chưa có nội dung. Vui lòng thử lại."
    failureMessage="Chưa tải được mẫu KB. Vui lòng thử lại."
  />
);
