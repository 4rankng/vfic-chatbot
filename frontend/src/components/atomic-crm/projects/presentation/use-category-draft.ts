import { useCallback, useEffect, useRef, useState } from "react";
import { useNotify } from "ra-core";

import { ApiError } from "@/lib/apiClient";
import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";
import {
  getProjectKnowledgeCategorySource,
  getProjectKnowledgeCategoryTemplate,
} from "../project-knowledge-service";
import type { ProjectKnowledgeCatalog } from "./use-project-knowledge-catalog";

export type CategoryDraft = Readonly<{
  /** What the textarea shows; equal to `savedContent` unless it is being edited. */
  content: string;
  filename: string;
  hasCurrentSource: boolean;
  hasUnsavedChanges: boolean;
  isEditing: boolean;
  loading: boolean;
  /** A source read failed; its absence has not been confirmed. */
  loadFailed: boolean;
  saving: boolean;
  reload: () => Promise<void>;
  setContent: (value: string) => void;
  startEditing: () => void;
  /** Leaves edit mode and restores the revision currently in use. */
  cancelEditing: () => void;
  save: () => Promise<void>;
}>;

/**
 * Draft state of one category: the category source currently in use, the copy
 * being edited, and a blank source used to seed the inline editor. Writes are
 * delegated to the catalog so a single layer owns the review pipeline.
 */
export const useCategoryDraft = (
  projectId: string,
  key: ProjectKnowledgeCategory,
  catalog: ProjectKnowledgeCatalog,
): CategoryDraft => {
  const notify = useNotify();
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [template, setTemplate] = useState("");
  const [filename, setFilename] = useState(`${key}.md`);
  const [hasCurrentSource, setHasCurrentSource] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const contextRef = useRef(0);
  const readRequestRef = useRef(0);
  const editingRef = useRef(false);
  const loadedRevisionRef = useRef<string | null | undefined>(undefined);

  const { replaceCategory } = catalog;
  const activeRevisionId =
    catalog.categories?.find((row) => row.key === key)?.active_revision_id ??
    null;

  useEffect(() => {
    contextRef.current += 1;
    loadedRevisionRef.current = undefined;
    editingRef.current = false;
    setLoading(true);
    setLoadFailed(false);
    setSaving(false);
    savingRef.current = false;
    setContent("");
    setSavedContent("");
    setIsEditing(false);
    setTemplate("");
    setFilename(`${key}.md`);
    setHasCurrentSource(false);

    return () => {
      contextRef.current += 1;
      readRequestRef.current += 1;
    };
  }, [key, projectId]);

  const reload = useCallback(async () => {
    const request = ++readRequestRef.current;
    setLoading(true);
    const [sourceResult, templateResult] = await Promise.allSettled([
      getProjectKnowledgeCategorySource(projectId, key),
      getProjectKnowledgeCategoryTemplate(projectId, key),
    ]);
    if (request !== readRequestRef.current) return;

    if (sourceResult.status === "fulfilled") {
      loadedRevisionRef.current = sourceResult.value.revision_id;
      if (!editingRef.current) setContent(sourceResult.value.content);
      setSavedContent(sourceResult.value.content);
      setFilename(sourceResult.value.filename);
      setHasCurrentSource(true);
      setLoadFailed(false);
    } else if (
      sourceResult.reason instanceof ApiError &&
      sourceResult.reason.status === 404
    ) {
      loadedRevisionRef.current = null;
      if (!editingRef.current) setContent("");
      setSavedContent("");
      setHasCurrentSource(false);
      setLoadFailed(false);
    } else {
      setLoadFailed(true);
      notify((sourceResult.reason as Error).message, { type: "error" });
    }

    if (templateResult.status === "fulfilled") {
      setTemplate(templateResult.value.content);
      if (
        sourceResult.status === "rejected" &&
        sourceResult.reason instanceof ApiError &&
        sourceResult.reason.status === 404
      ) {
        setFilename(templateResult.value.filename);
      }
    } else {
      notify((templateResult.reason as Error).message, { type: "error" });
    }

    setLoading(false);
  }, [key, notify, projectId]);

  useEffect(() => {
    // Catalog publication changes the source. Keep an open edit buffer, but
    // update the published baseline so cancel always restores the live text.
    if (loadedRevisionRef.current !== activeRevisionId) void reload();
  }, [activeRevisionId, reload]);

  const startEditing = useCallback(() => {
    if (loading || loadFailed || saving) return;
    if (!hasCurrentSource && !content.trim() && template) {
      setContent(template);
    }
    editingRef.current = true;
    setIsEditing(true);
  }, [content, hasCurrentSource, loadFailed, loading, saving, template]);

  const cancelEditing = useCallback(() => {
    setContent(savedContent);
    editingRef.current = false;
    setIsEditing(false);
  }, [savedContent]);

  const save = useCallback(async () => {
    if (loading || savingRef.current || loadFailed || !isEditing) return;
    if (!content.trim()) {
      notify("Vui lòng nhập nội dung.", { type: "warning" });
      return;
    }
    if (
      hasCurrentSource &&
      !window.confirm(
        "Nội dung đã sửa sẽ tạo phiên bản mới và thay thế dữ liệu đang dùng sau khi kiểm tra. Tiếp tục?",
      )
    ) {
      return;
    }

    savingRef.current = true;
    setSaving(true);
    const context = contextRef.current;
    try {
      await replaceCategory(key, filename, content);
      if (context !== contextRef.current) return;
      // Acceptance starts review; only a subsequent source read can confirm
      // that this edit is the content currently used by the Agent.
      editingRef.current = false;
      setIsEditing(false);
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
    content,
    filename,
    hasCurrentSource,
    isEditing,
    key,
    loadFailed,
    loading,
    notify,
    replaceCategory,
  ]);

  return {
    content: isEditing ? content : savedContent,
    filename,
    hasCurrentSource,
    hasUnsavedChanges: content !== savedContent,
    isEditing,
    loading,
    loadFailed,
    saving,
    reload,
    setContent,
    startEditing,
    cancelEditing,
    save,
  };
};
