import { useCallback, useEffect, useRef, useState } from "react";

import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";
import {
  getProjectKnowledgeCategories,
  replaceProjectKnowledgeCategory,
  uploadProjectDocument,
} from "../project-knowledge-service";

/**
 * A category revision is reviewed asynchronously: the replace call returns a
 * revision id that only becomes the category's active revision once the
 * pipeline has chunked, embedded and index-checked it. Same cadence and bound
 * as the project page's catalog hook, so a create-form ingest and a later edit
 * behave identically.
 */
const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 20;

export type IngestWrite = Readonly<{
  key: ProjectKnowledgeCategory;
  filename: string;
  content: string;
}>;

export type IngestState =
  | Readonly<{ phase: "idle" }>
  | Readonly<{
      phase: "running";
      /** The category the pipeline is reviewing right now. */
      current: ProjectKnowledgeCategory;
      /** Categories already active, in the order they were written. */
      activated: readonly ProjectKnowledgeCategory[];
      total: number;
    }>
  | Readonly<{
      phase: "failed";
      failed: ProjectKnowledgeCategory;
      /** The backend's own words; an empty string when it gave none. */
      message: string;
      activated: readonly ProjectKnowledgeCategory[];
      /** Non-fatal companion error: the brief-document upload failed. */
      uploadError?: string;
    }>
  | Readonly<{
      phase: "done";
      activated: readonly ProjectKnowledgeCategory[];
      /** Non-fatal companion error: the brief-document upload failed. */
      uploadError?: string;
    }>;

export type ProjectIngest = Readonly<{
  state: IngestState;
  /**
   * Write every category in order, awaiting each one becoming active before
   * starting the next. Order is not cosmetic: a category that references
   * `job_ids` is rejected unless those jobs are already active, so `jobs` must
   * lead the batch.
   *
   * `sourceFile` — the original brief file — is uploaded alongside the writes
   * as a project knowledge document, so the brief stays on record (counted in
   * the project's documents and searchable) instead of only surviving as
   * derived YAML. Best-effort: its failure never blocks the writes and rides on
   * the terminal state's `uploadError`. Callers without a file omit it and the
   * chain behaves exactly as before.
   */
  ingest: (
    projectId: string,
    writes: readonly IngestWrite[],
    sourceFile?: File,
  ) => Promise<void>;
  /** Stop the chain; a write in flight still resolves but nothing follows it. */
  cancel: () => void;
}>;

type WaitOutcome =
  | Readonly<{ ok: true }>
  | Readonly<{ ok: false; message: string }>;

/**
 * Runs a brief's knowledge ingest — the create form's first upload and every
 * later re-ingest from the project page share this one chain.
 *
 * The project page's `useProjectKnowledgeCatalog` is the right owner for edits,
 * but it fires each write and forgets it — which is fine there, because the
 * recruiter is already looking at the project. Creation is different: the next
 * category depends on the previous one having landed, and the admin's next
 * button (`Tạo dự án`) must not be offered before the data is real. So the
 * chain here AWAITS each activation instead of polling in the background.
 *
 * Status is reported only from what the backend confirms. The replace response
 * is the backend accepting a category's content; the catalog poll then holds
 * the chain while that revision is STAGED/PROCESSING and stops on ACTIVE or
 * FAILED. Nothing is shown as ready that the pipeline has not actually accepted.
 */
export const useProjectIngest = (): ProjectIngest => {
  const [state, setState] = useState<IngestState>({ phase: "idle" });
  const epochRef = useRef(0);
  const timerRef = useRef<number | null>(null);

  const cancel = useCallback(() => {
    epochRef.current += 1;
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => cancel, [cancel]);

  const waitForActive = useCallback(
    (projectId: string, revisionId: string, epoch: number) =>
      new Promise<WaitOutcome>((resolve) => {
        const attempt = (tries: number) => {
          timerRef.current = window.setTimeout(() => {
            timerRef.current = null;
            if (epoch !== epochRef.current) {
              resolve({ ok: false, message: "" });
              return;
            }
            // A hidden tab must not keep hitting the backend; park the hop
            // rather than spinning the queue in the background.
            if (document.visibilityState === "hidden") {
              attempt(tries);
              return;
            }
            void getProjectKnowledgeCategories(projectId)
              .then((catalog) => {
                if (epoch !== epochRef.current) {
                  resolve({ ok: false, message: "" });
                  return;
                }
                const row = catalog.data.find(
                  (item) => item.active_revision_id === revisionId,
                );
                if (row) {
                  resolve({ ok: true });
                  return;
                }
                const failed = catalog.data.find(
                  (item) =>
                    item.latest_revision_id === revisionId &&
                    item.status === "FAILED",
                );
                if (failed) {
                  resolve({ ok: false, message: failed.error_message ?? "" });
                  return;
                }
                // The replace response already accepted the content; waiting
                // longer is only meaningful while the catalog still tracks the
                // revision as in review. A category row that does not carry the
                // revision at all contradicts nothing, so acceptance stands.
                const reviewing = catalog.data.some(
                  (item) =>
                    item.latest_revision_id === revisionId &&
                    (item.status === "STAGED" || item.status === "PROCESSING"),
                );
                if (reviewing && tries < MAX_POLL_ATTEMPTS) {
                  attempt(tries + 1);
                  return;
                }
                if (reviewing) {
                  resolve({
                    ok: false,
                    message:
                      "Hệ thống chưa phản hồi kịp. Kiến thức vẫn đang được xử lý.",
                  });
                  return;
                }
                resolve({ ok: true });
              })
              .catch((error: unknown) => {
                if (epoch === epochRef.current) {
                  resolve({ ok: false, message: (error as Error).message });
                } else {
                  resolve({ ok: false, message: "" });
                }
              });
          }, POLL_INTERVAL_MS);
        };
        attempt(0);
      }),
    [],
  );

  const ingest = useCallback(
    async (
      projectId: string,
      writes: readonly IngestWrite[],
      sourceFile?: File,
    ) => {
      cancel();
      const epoch = epochRef.current;
      const activated: ProjectKnowledgeCategory[] = [];
      // The original brief is uploaded best-effort, alongside the writes: it
      // must land on record as a project knowledge document, but its failure
      // never blocks the category chain. Started first and awaited only at the
      // terminal states, so it rides along the poll waits instead of
      // serializing behind them, and its error is reported without stopping.
      let uploadError: string | undefined;
      const uploadSettled = sourceFile
        ? uploadProjectDocument(projectId, sourceFile).catch((error: unknown) => {
            uploadError = (error as Error).message;
          })
        : Promise.resolve();

      for (const write of writes) {
        if (epoch !== epochRef.current) return;
        setState({
          phase: "running",
          current: write.key,
          activated: [...activated],
          total: writes.length,
        });

        let revisionId: string;
        try {
          const result = await replaceProjectKnowledgeCategory(
            projectId,
            write.key,
            write.filename,
            write.content,
          );
          revisionId = result.revision.id;
        } catch (error) {
          await uploadSettled;
          setState({
            phase: "failed",
            failed: write.key,
            message: (error as Error).message,
            activated: [...activated],
            uploadError,
          });
          return;
        }

        if (epoch !== epochRef.current) return;
        const outcome = await waitForActive(projectId, revisionId, epoch);
        if (!outcome.ok) {
          await uploadSettled;
          setState({
            phase: "failed",
            failed: write.key,
            message: outcome.message,
            activated: [...activated],
            uploadError,
          });
          return;
        }
        activated.push(write.key);
      }

      if (epoch !== epochRef.current) return;
      await uploadSettled;
      setState({ phase: "done", activated: [...activated], uploadError });
    },
    [cancel, waitForActive],
  );

  return { state, ingest, cancel };
};
