import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNotify } from "ra-core";

import type { KnowledgeCategoryStatus } from "../domain/project-knowledge-contracts";
import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";
import {
  getProjectKnowledgeCategories,
  replaceProjectKnowledgeCategory,
  uploadProjectKnowledgeCategory,
} from "../project-knowledge-service";

/**
 * A category revision is reviewed asynchronously: the upload/replace call
 * returns a revision id that only becomes the category's active revision once
 * the pipeline accepts it. Poll at a fixed cadence for a bounded number of
 * attempts, then leave the revision to be picked up on the next visit.
 */
const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 20;

export type ProjectKnowledgeCatalog = Readonly<{
  /** `null` until the first catalog response lands. */
  categories: KnowledgeCategoryStatus[] | null;
  /** The category whose latest revision is still being reviewed, if any. */
  processingKey: ProjectKnowledgeCategory | null;
  replaceCategory: (
    key: ProjectKnowledgeCategory,
    filename: string,
    content: string,
  ) => Promise<void>;
  uploadCategory: (key: ProjectKnowledgeCategory, file: File) => Promise<void>;
}>;

/**
 * Owns every read and write of the project's category catalog, including the
 * revision-review poll loop. Components never touch the knowledge service
 * directly, so one layer owns cache coherence for the catalog.
 */
export const useProjectKnowledgeCatalog = (
  projectId: string,
): ProjectKnowledgeCatalog => {
  const notify = useNotify();
  const [categories, setCategories] = useState<
    KnowledgeCategoryStatus[] | null
  >(null);
  const [processingKey, setProcessingKey] =
    useState<ProjectKnowledgeCategory | null>(null);
  const pollRef = useRef<number | null>(null);

  const loadCatalog = useCallback(async () => {
    const catalog = await getProjectKnowledgeCategories(projectId);
    setCategories(catalog.data);
    return catalog.data;
  }, [projectId]);

  const pollUntilActive = useCallback(
    function poll(revisionId: string, attempts = 0) {
      pollRef.current = window.setTimeout(() => {
        void loadCatalog()
          .then((rows) => {
            if (rows.some((row) => row.active_revision_id === revisionId)) {
              setProcessingKey(null);
              notify("Dữ liệu mới đã sẵn sàng cho Agent.", {
                type: "success",
              });
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
            } else if (attempts < MAX_POLL_ATTEMPTS) {
              poll(revisionId, attempts + 1);
            } else {
              setProcessingKey(null);
              notify(
                "Dữ liệu đang được xử lý. Bạn có thể quay lại kiểm tra sau.",
                { type: "info" },
              );
            }
          })
          .catch(() => setProcessingKey(null));
      }, POLL_INTERVAL_MS);
    },
    [loadCatalog, notify],
  );

  useEffect(() => {
    void loadCatalog().catch((error) =>
      notify((error as Error).message, { type: "error" }),
    );
    return () => {
      if (pollRef.current !== null) window.clearTimeout(pollRef.current);
    };
  }, [loadCatalog, notify]);

  const trackRevision = useCallback(
    (key: ProjectKnowledgeCategory, revisionId: string) => {
      setProcessingKey(key);
      pollUntilActive(revisionId);
    },
    [pollUntilActive],
  );

  const replaceCategory = useCallback(
    async (
      key: ProjectKnowledgeCategory,
      filename: string,
      content: string,
    ) => {
      const result = await replaceProjectKnowledgeCategory(
        projectId,
        key,
        filename,
        content,
      );
      trackRevision(key, result.revision.id);
      notify("Đã lưu thay đổi. Hệ thống đang kiểm tra cho Agent.", {
        type: "info",
      });
    },
    [notify, projectId, trackRevision],
  );

  const uploadCategory = useCallback(
    async (key: ProjectKnowledgeCategory, file: File) => {
      const result = await uploadProjectKnowledgeCategory(projectId, key, file);
      trackRevision(key, result.revision.id);
      notify("Đã tải file. Hệ thống đang kiểm tra và chuẩn bị cho Agent.", {
        type: "info",
      });
    },
    [notify, projectId, trackRevision],
  );

  return useMemo(
    () => ({ categories, processingKey, replaceCategory, uploadCategory }),
    [categories, processingKey, replaceCategory, uploadCategory],
  );
};
