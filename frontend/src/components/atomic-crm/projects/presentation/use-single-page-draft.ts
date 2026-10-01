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
  /** A source update is available while a local draft remains unsaved. */
  remoteChanged: boolean;
  autoSyncOn: boolean;
  /** Bumped whenever the linked Google Sheet sources change. */
  syncRefreshKey: number;
  setFilename: (value: string) => void;
  setText: (value: string) => void;
  save: () => Promise<void>;
  readFile: (file?: File) => Promise<void>;
  handleSourceChange: () => void;
  handleSynchronized: () => void;
  reload: () => Promise<void>;
  discardChanges: () => void;
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
  const [remoteChanged, setRemoteChanged] = useState(false);
  const loadRequestRef = useRef(0);
  const contextRef = useRef(0);
  const fileRequestRef = useRef(0);
  const editVersionRef = useRef(0);
  const savingRef = useRef(false);
  const refreshAfterSaveRef = useRef(false);
  const baselineRef = useRef({ filename: "single-page.md", text: "" });
  const draftRef = useRef(baselineRef.current);
  const syncRequestRef = useRef(0);

  const updateFilename = useCallback((value: string) => {
    editVersionRef.current += 1;
    draftRef.current = { ...draftRef.current, filename: value };
    setFilename(value);
    if (
      value === baselineRef.current.filename &&
      draftRef.current.text === baselineRef.current.text
    )
      setRemoteChanged(false);
  }, []);
  const updateText = useCallback((value: string) => {
    editVersionRef.current += 1;
    draftRef.current = { ...draftRef.current, text: value };
    setText(value);
    if (
      value === baselineRef.current.text &&
      draftRef.current.filename === baselineRef.current.filename
    )
      setRemoteChanged(false);
  }, []);

  const acceptPage = useCallback((page: { filename: string; text: string }) => {
    const baseline = baselineRef.current;
    const draft = draftRef.current;
    const dirty =
      draft.filename !== baseline.filename || draft.text !== baseline.text;
    const changed =
      page.filename !== baseline.filename || page.text !== baseline.text;
    const differsFromIncoming =
      draft.filename !== page.filename || draft.text !== page.text;
    baselineRef.current = page;
    if (!dirty || !differsFromIncoming) {
      draftRef.current = page;
      setFilename(page.filename);
      setText(page.text);
    }
    setRemoteChanged(
      (previous) => dirty && differsFromIncoming && (changed || previous),
    );
  }, []);

  const loadPage = useCallback(
    async ({ background = false }: { background?: boolean } = {}) => {
      if (background && savingRef.current) {
        refreshAfterSaveRef.current = true;
        return;
      }
      const requestId = ++loadRequestRef.current;
      if (background) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
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
          // A background response can supersede a foreground retry. Both
          // indicators belong to the newest request, so release both here.
          setRefreshing(false);
          setLoading(false);
        }
      }
    },
    [acceptPage, notify, projectId],
  );

  const loadSyncState = useCallback(async () => {
    const request = ++syncRequestRef.current;
    const context = contextRef.current;
    if (!canManageSources) {
      setAutoSyncOn(false);
      return;
    }
    try {
      const rows = await listSinglePageExternalSources(projectId);
      if (context === contextRef.current && request === syncRequestRef.current)
        setAutoSyncOn(rows.some((row) => row.auto_sync_enabled));
    } catch {
      if (context === contextRef.current && request === syncRequestRef.current)
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
    const empty = { filename: "single-page.md", text: "" };
    baselineRef.current = empty;
    draftRef.current = empty;
    savingRef.current = false;
    refreshAfterSaveRef.current = false;
    setFilename(empty.filename);
    setText(empty.text);
    setSaving(false);
    setRefreshing(false);
    setRemoteChanged(false);
    setHasCurrentPage(false);
    setLoadFailed(false);
    void loadPage();
    return () => {
      contextRef.current += 1;
      fileRequestRef.current += 1;
      loadRequestRef.current += 1;
    };
  }, [loadPage]);

  useEffect(() => {
    void loadSyncState();
  }, [loadSyncState]);

  const discardChanges = useCallback(() => {
    editVersionRef.current += 1;
    const baseline = baselineRef.current;
    draftRef.current = baseline;
    setFilename(baseline.filename);
    setText(baseline.text);
    setRemoteChanged(false);
  }, []);

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
    setRefreshing(false);
    setSaving(true);
    try {
      await replaceProjectSinglePage(projectId, filename, text);
      if (context !== contextRef.current) return;
      baselineRef.current = submitted;
      setRemoteChanged(false);
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
      if (context === contextRef.current)
        notify((error as Error).message, { type: "error" });
    } finally {
      if (context === contextRef.current) {
        savingRef.current = false;
        setSaving(false);
        if (refreshAfterSaveRef.current) {
          refreshAfterSaveRef.current = false;
          void loadPage({ background: true });
        }
      }
    }
  }, [
    filename,
    hasCurrentPage,
    isActive,
    loading,
    loadPage,
    loadFailed,
    loadSyncState,
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
    refreshing,
    filename,
    text,
    hasCurrentPage,
    loadFailed,
    remoteChanged,
    autoSyncOn,
    syncRefreshKey,
    setFilename: updateFilename,
    setText: updateText,
    save,
    readFile,
    handleSourceChange,
    handleSynchronized,
    reload: loadPage,
    discardChanges,
  };
};
