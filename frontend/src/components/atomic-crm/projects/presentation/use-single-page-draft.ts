import { useCallback, useEffect, useRef, useState } from "react";
import { useNotify, useRefresh } from "ra-core";

import { ApiError } from "@/lib/apiClient";
import {
  getProjectSinglePage,
  replaceProjectSinglePage,
} from "../project-knowledge-service";

export type SinglePageDraft = Readonly<{
  loading: boolean;
  saving: boolean;
  filename: string;
  text: string;
  hasCurrentPage: boolean;
  loadFailed: boolean;
  setFilename: (value: string) => void;
  setText: (value: string) => void;
  save: () => Promise<void>;
  readFile: (file?: File) => Promise<void>;
  reload: () => Promise<void>;
}>;

export type SinglePageDraftOptions = Readonly<{
  /** Inactive projects are activated by their first valid page save. */
  isActive: boolean;
}>;

/**
 * Draft state of the DIRECT_CONTEXT single knowledge page. Owns the
 * request-generation guard that discards stale reloads.
 */
export const useSinglePageDraft = (
  projectId: string,
  { isActive }: SinglePageDraftOptions,
): SinglePageDraft => {
  const notify = useNotify();
  const refresh = useRefresh();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [filename, setFilename] = useState("single-page.md");
  const [text, setText] = useState("");
  const [hasCurrentPage, setHasCurrentPage] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const loadRequestRef = useRef(0);
  const contextRef = useRef(0);
  const fileRequestRef = useRef(0);
  const editVersionRef = useRef(0);
  const savingRef = useRef(false);
  const baselineRef = useRef({ filename: "single-page.md", text: "" });
  const draftRef = useRef(baselineRef.current);

  const updateFilename = useCallback((value: string) => {
    editVersionRef.current += 1;
    draftRef.current = { ...draftRef.current, filename: value };
    setFilename(value);
  }, []);
  const updateText = useCallback((value: string) => {
    editVersionRef.current += 1;
    draftRef.current = { ...draftRef.current, text: value };
    setText(value);
  }, []);

  const acceptPage = useCallback((page: { filename: string; text: string }) => {
    baselineRef.current = page;
    draftRef.current = page;
    setFilename(page.filename);
    setText(page.text);
  }, []);

  const loadPage = useCallback(async () => {
    const requestId = ++loadRequestRef.current;
    setLoading(true);
    try {
      const page = await getProjectSinglePage(projectId);
      if (requestId !== loadRequestRef.current) return;
      acceptPage({ filename: page.filename, text: page.text });
      setHasCurrentPage(true);
      setLoadFailed(false);
    } catch (error: unknown) {
      if (requestId !== loadRequestRef.current) return;
      if (error instanceof ApiError && error.status === 404) {
        acceptPage({ filename: "single-page.md", text: "" });
        setHasCurrentPage(false);
        setLoadFailed(false);
        return;
      }
      setLoadFailed(true);
      notify((error as Error).message, { type: "error" });
    } finally {
      if (requestId === loadRequestRef.current) {
        setLoading(false);
      }
    }
  }, [acceptPage, notify, projectId]);

  useEffect(() => {
    const empty = { filename: "single-page.md", text: "" };
    baselineRef.current = empty;
    draftRef.current = empty;
    savingRef.current = false;
    setFilename(empty.filename);
    setText(empty.text);
    setSaving(false);
    setHasCurrentPage(false);
    setLoadFailed(false);
    void loadPage();
    return () => {
      contextRef.current += 1;
      fileRequestRef.current += 1;
      loadRequestRef.current += 1;
    };
  }, [loadPage]);

  const save = useCallback(async () => {
    if (savingRef.current || loading) return;
    if (loadFailed) {
      notify(
        "Chưa tải được nội dung hiện tại. Vui lòng tải lại trang trước khi lưu.",
        { type: "warning" },
      );
      return;
    }
    if (!text.trim()) {
      notify("Vui lòng nhập nội dung kiến thức.", { type: "warning" });
      return;
    }
    if (!filename.trim()) {
      notify("Vui lòng nhập tên tệp.", { type: "warning" });
      return;
    }
    if (!/\.(txt|md)$/i.test(filename.trim())) {
      notify("Tên tệp kiến thức cần có đuôi .txt hoặc .md.", {
        type: "warning",
      });
      return;
    }
    if (
      hasCurrentPage &&
      !window.confirm(
        isActive
          ? "Nội dung mới sẽ thay thế toàn bộ trang hiện tại. Tiếp tục?"
          : "Nội dung mới sẽ thay thế toàn bộ trang hiện tại và bật dự án để chatbot sử dụng. Tiếp tục?",
      )
    ) {
      return;
    }
    const context = contextRef.current;
    const submitted = { filename, text };
    savingRef.current = true;
    loadRequestRef.current += 1;
    setSaving(true);
    try {
      await replaceProjectSinglePage(projectId, filename, text);
      if (context !== contextRef.current) return;
      baselineRef.current = submitted;
      setHasCurrentPage(true);
      notify(
        isActive
          ? "Đã thay thế trang kiến thức của dự án."
          : "Đã lưu trang kiến thức và bật dự án.",
        { type: "success" },
      );
      // The page replaced the react-admin-cached project record, so the
      // reviewer's record has to be re-read to show the new state.
      refresh();
    } catch (error) {
      if (context === contextRef.current)
        notify((error as Error).message, { type: "error" });
    } finally {
      if (context === contextRef.current) {
        savingRef.current = false;
        setSaving(false);
      }
    }
  }, [
    filename,
    hasCurrentPage,
    isActive,
    loading,
    loadFailed,
    notify,
    projectId,
    refresh,
    text,
  ]);

  const readFile = useCallback(
    async (file?: File) => {
      if (!file || savingRef.current) return;
      if (!/\.(txt|md)$/i.test(file.name)) {
        notify("Trang kiến thức chỉ nhận file .txt hoặc .md.", {
          type: "warning",
        });
        return;
      }
      // Every legal 300,000-character UTF-8 page fits within this read budget.
      // Reject an oversized pick before decoding it in the browser.
      if (file.size > 2 * 1024 * 1024) {
        notify("Tệp quá lớn. Trang kiến thức chỉ nhận tệp dưới 2 MB.", {
          type: "warning",
        });
        return;
      }
      const context = contextRef.current;
      const request = ++fileRequestRef.current;
      const editVersion = editVersionRef.current;
      try {
        const fileText = await file.text();
        if (
          context !== contextRef.current ||
          request !== fileRequestRef.current ||
          editVersion !== editVersionRef.current
        )
          return;
        updateFilename(file.name);
        updateText(fileText);
      } catch {
        if (
          context === contextRef.current &&
          request === fileRequestRef.current
        )
          notify("Không đọc được tệp. Vui lòng thử lại.", { type: "error" });
      }
    },
    [notify, updateFilename, updateText],
  );

  return {
    loading,
    saving,
    filename,
    text,
    hasCurrentPage,
    loadFailed,
    setFilename: updateFilename,
    setText: updateText,
    save,
    readFile,
    reload: loadPage,
  };
};
