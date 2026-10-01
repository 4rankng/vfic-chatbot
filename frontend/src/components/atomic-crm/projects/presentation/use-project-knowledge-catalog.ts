import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNotify } from "ra-core";

import type { KnowledgeCategoryStatus } from "../domain/project-knowledge-contracts";
import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";
import {
  getProjectKnowledgeCategories,
  replaceProjectKnowledgeCategory,
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
  reload: () => Promise<KnowledgeCategoryStatus[]>;
  replaceCategory: (
    key: ProjectKnowledgeCategory,
    filename: string,
    content: string,
  ) => Promise<void>;
}>;

/**
 * Owns every read and write of the project's category catalog, including the
 * revision-review poll loop. Components never touch the knowledge service
 * directly, so one layer owns cache coherence for the catalog.
 *
 * At most one poll chain runs at a time: starting a new chain (or leaving the
 * page, or switching project) cancels the previous one, and a hidden tab
 * pauses the chain until the tab becomes visible again.
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
  /** Bumped whenever the active chain is replaced or torn down. */
  const pollEpochRef = useRef(0);
  /** A hop that woke while the tab was hidden parks here until visible. */
  const resumePollRef = useRef<(() => void) | null>(null);
  const readRequestRef = useRef(0);
  const writeRequestRef = useRef(0);

  const loadCatalog = useCallback(async () => {
    const request = ++readRequestRef.current;
    const catalog = await getProjectKnowledgeCategories(projectId);
    if (request === readRequestRef.current) setCategories(catalog.data);
    return catalog.data;
  }, [projectId]);

  const cancelPoll = useCallback(() => {
    pollEpochRef.current += 1;
    // An old poll's read must not paint the catalog before its caller checks
    // the chain epoch, including when the project has changed.
    readRequestRef.current += 1;
    if (pollRef.current !== null) {
      window.clearTimeout(pollRef.current);
      pollRef.current = null;
    }
    resumePollRef.current = null;
  }, []);

  const pollUntilActive = useCallback(
    function poll(revisionId: string, attempts = 0) {
      // A new chain cancels the previous one instead of orphaning it: drop its
      // pending hop and stamp this chain's epoch so results from any hop of a
      // superseded chain are discarded.
      cancelPoll();
      const epoch = pollEpochRef.current;

      const schedule = () => {
        pollRef.current = window.setTimeout(() => {
          pollRef.current = null;
          if (epoch !== pollEpochRef.current) return;
          if (document.visibilityState === "hidden") {
            // A hidden tab must not keep hitting the backend; park this hop
            // until the tab becomes visible again.
            resumePollRef.current = () => poll(revisionId, attempts);
            return;
          }
          void loadCatalog()
            .then((rows) => {
              if (epoch !== pollEpochRef.current) return;
              if (rows.some((row) => row.active_revision_id === revisionId)) {
                setProcessingKey(null);
                notify("Dữ liệu mới đã sẵn sàng cho chatbot.", {
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
                notify(
                  "Nội dung mới có lỗi. Dữ liệu đang dùng không thay đổi.",
                  { type: "error" },
                );
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
            .catch(() => {
              if (epoch === pollEpochRef.current) setProcessingKey(null);
            });
        }, POLL_INTERVAL_MS);
      };

      schedule();
    },
    [cancelPoll, loadCatalog, notify],
  );

  useEffect(() => {
    let active = true;
    // The indicator belongs to the previous project once the catalog reloads.
    setProcessingKey(null);
    setCategories(null);
    void loadCatalog().catch((error) => {
      if (active) notify((error as Error).message, { type: "error" });
    });
    const handleVisibilityChange = () => {
      const resume = resumePollRef.current;
      if (resume && document.visibilityState !== "hidden") {
        resumePollRef.current = null;
        resume();
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      active = false;
      writeRequestRef.current += 1;
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      // Bumping the epoch here also discards an in-flight hop's response, so
      // no category write or toast lands after leaving the page.
      cancelPoll();
    };
  }, [cancelPoll, loadCatalog, notify]);

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
      const request = ++writeRequestRef.current;
      const result = await replaceProjectKnowledgeCategory(
        projectId,
        key,
        filename,
        content,
      );
      if (request !== writeRequestRef.current) return;
      trackRevision(key, result.revision.id);
      notify("Đã lưu thay đổi. Hệ thống đang kiểm tra cho chatbot.", {
        type: "info",
      });
    },
    [notify, projectId, trackRevision],
  );

  return useMemo(
    () => ({ categories, processingKey, replaceCategory, reload: loadCatalog }),
    [categories, processingKey, replaceCategory, loadCatalog],
  );
};
