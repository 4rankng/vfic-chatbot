import { useCallback, useEffect, useState } from "react";
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
  /** The blank category template used to seed a category that has no data yet. */
  template: string;
  templateFilename: string;
  hasCurrentSource: boolean;
  hasUnsavedChanges: boolean;
  isEditing: boolean;
  loading: boolean;
  saving: boolean;
  setContent: (value: string) => void;
  startEditing: () => void;
  /** Leaves edit mode and restores the revision currently in use. */
  cancelEditing: () => void;
  save: () => Promise<void>;
  downloadTemplate: () => void;
}>;

/**
 * Draft state of one category: the category source currently in use, the copy
 * being edited, and the template behind the download action. Writes are
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
  const [templateFilename, setTemplateFilename] = useState(`${key}.md`);
  const [filename, setFilename] = useState(`${key}.md`);
  const [hasCurrentSource, setHasCurrentSource] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const { replaceCategory } = catalog;

  useEffect(() => {
    let active = true;
    setLoading(true);
    setContent("");
    setSavedContent("");
    setIsEditing(false);
    setTemplate("");
    setFilename(`${key}.md`);
    setHasCurrentSource(false);

    void Promise.allSettled([
      getProjectKnowledgeCategorySource(projectId, key),
      getProjectKnowledgeCategoryTemplate(projectId, key),
    ]).then(([sourceResult, templateResult]) => {
      if (!active) return;

      if (sourceResult.status === "fulfilled") {
        setContent(sourceResult.value.content);
        setSavedContent(sourceResult.value.content);
        setFilename(sourceResult.value.filename);
        setHasCurrentSource(true);
      } else if (
        !(sourceResult.reason instanceof ApiError) ||
        sourceResult.reason.status !== 404
      ) {
        notify((sourceResult.reason as Error).message, { type: "error" });
      }

      if (templateResult.status === "fulfilled") {
        setTemplate(templateResult.value.content);
        setTemplateFilename(templateResult.value.filename);
        if (sourceResult.status !== "fulfilled") {
          setFilename(templateResult.value.filename);
        }
      } else {
        notify((templateResult.reason as Error).message, { type: "error" });
      }

      setLoading(false);
    });

    return () => {
      active = false;
    };
  }, [key, notify, projectId]);

  const startEditing = useCallback(() => {
    if (!hasCurrentSource && !content.trim() && template) {
      setContent(template);
    }
    setIsEditing(true);
  }, [content, hasCurrentSource, template]);

  const cancelEditing = useCallback(() => {
    setContent(savedContent);
    setIsEditing(false);
  }, [savedContent]);

  const save = useCallback(async () => {
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

    setSaving(true);
    try {
      await replaceCategory(key, filename, content);
      setSavedContent(content);
      setIsEditing(false);
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setSaving(false);
    }
  }, [content, filename, hasCurrentSource, key, notify, replaceCategory]);

  const downloadTemplate = useCallback(() => {
    const url = URL.createObjectURL(
      new Blob([template], { type: "text/markdown;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = templateFilename;
    link.click();
    URL.revokeObjectURL(url);
  }, [template, templateFilename]);

  return {
    content,
    filename,
    template,
    templateFilename,
    hasCurrentSource,
    hasUnsavedChanges: content !== savedContent,
    isEditing,
    loading,
    saving,
    setContent,
    startEditing,
    cancelEditing,
    save,
    downloadTemplate,
  };
};
