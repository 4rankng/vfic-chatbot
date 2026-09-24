import { useCallback, useEffect, useRef, useState } from "react";
import { useNotify, useRefresh } from "ra-core";

import { ApiError } from "@/lib/apiClient";
import {
  getProjectSinglePage,
  listSinglePageExternalSources,
  replaceProjectSinglePage,
} from "../project-knowledge-service";

export type SinglePageDraft = Readonly<{
  loading: boolean;
  saving: boolean;
  /** A background reload of the page text is in flight. */
  refreshing: boolean;
  filename: string;
  text: string;
  hasCurrentPage: boolean;
  loadFailed: boolean;
  autoSyncOn: boolean;
  /** Bumped whenever the linked Google Sheet sources change. */
  syncRefreshKey: number;
  setFilename: (value: string) => void;
  setText: (value: string) => void;
  save: () => Promise<void>;
  readFile: (file?: File) => Promise<void>;
  handleSourceChange: () => void;
  handleSynchronized: () => void;
}>;

export type SinglePageDraftOptions = Readonly<{
  /** Inactive projects are activated by their first valid page save. */
  isActive: boolean;
  /** Only editors may read admin-only sync state. */
  canManageSources: boolean;
}>;

/**
 * Draft state of the DIRECT_CONTEXT single knowledge page, including the
 * Google Sheet sync section that feeds it. Owns the request-generation guard
 * that discards stale reloads.
 */
export const useSinglePageDraft = (
  projectId: string,
  { isActive, canManageSources }: SinglePageDraftOptions,
): SinglePageDraft => {
  const notify = useNotify();
  const refresh = useRefresh();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [filename, setFilename] = useState("single-page.md");
  const [text, setText] = useState("");
  const [hasCurrentPage, setHasCurrentPage] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [syncRefreshKey, setSyncRefreshKey] = useState(0);
  const [autoSyncOn, setAutoSyncOn] = useState(false);
  const loadRequestRef = useRef(0);

  const loadPage = useCallback(
    async ({ background = false }: { background?: boolean } = {}) => {
      const requestId = ++loadRequestRef.current;
      if (background) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      try {
        const page = await getProjectSinglePage(projectId);
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
            setRefreshing(false);
          } else {
            setLoading(false);
          }
        }
      }
    },
    [notify, projectId],
  );

  const loadSyncState = useCallback(async () => {
    if (!canManageSources) return;
    try {
      const rows = await listSinglePageExternalSources(projectId);
      setAutoSyncOn(rows.some((row) => row.auto_sync_enabled));
    } catch {
      setAutoSyncOn(false);
    }
  }, [canManageSources, projectId]);

  const handleSourceChange = useCallback(() => {
    void loadSyncState();
    setSyncRefreshKey((value) => value + 1);
  }, [loadSyncState]);

  const handleSynchronized = useCallback(() => {
    void loadPage({ background: true });
    void loadSyncState();
  }, [loadPage, loadSyncState]);

  useEffect(() => {
    void loadPage();
    void loadSyncState();
    return () => {
      loadRequestRef.current += 1;
    };
  }, [loadPage, loadSyncState]);

  const save = useCallback(async () => {
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
    if (
      hasCurrentPage &&
      !window.confirm(
        isActive
          ? "Nội dung mới sẽ thay thế toàn bộ trang hiện tại. Tiếp tục?"
          : "Nội dung mới sẽ thay thế toàn bộ trang hiện tại và bật dự án để Agent sử dụng. Tiếp tục?",
      )
    ) {
      return;
    }
    setSaving(true);
    try {
      await replaceProjectSinglePage(projectId, filename, text);
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
      void loadSyncState();
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setSaving(false);
    }
  }, [
    filename,
    hasCurrentPage,
    isActive,
    loadFailed,
    loadSyncState,
    notify,
    projectId,
    refresh,
    text,
  ]);

  const readFile = useCallback(
    async (file?: File) => {
      if (!file) return;
      if (!/\.(txt|md)$/i.test(file.name)) {
        notify("Trang kiến thức chỉ nhận file .txt hoặc .md.", {
          type: "warning",
        });
        return;
      }
      setFilename(file.name);
      setText(await file.text());
    },
    [notify],
  );

  return {
    loading,
    saving,
    refreshing,
    filename,
    text,
    hasCurrentPage,
    loadFailed,
    autoSyncOn,
    syncRefreshKey,
    setFilename,
    setText,
    save,
    readFile,
    handleSourceChange,
    handleSynchronized,
  };
};
