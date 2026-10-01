import { useCallback, useEffect, useRef, useState } from "react";

import type { ProjectKnowledgeCategory } from "../domain/project-knowledge-policy";
import {
  getProjectKnowledgeCategories,
  getProjectTrainingDocument,
  replaceProjectKnowledgeCategory,
  uploadProjectDocument,
} from "../project-knowledge-service";

/**
 * A category revision is reviewed asynchronously: the replace call returns a
 * revision id that only becomes the category's active revision once the
 * pipeline has chunked, embedded and index-checked it. The chain polls the
 * catalog until each revision lands, and reports every category's live state
 * while it does.
 *
 * Polling is two-stage: the soft budget covers normal processing (a few
 * seconds per category). Past it, the chain keeps polling through the hard
 * budget and only flags the run slow — a queued revision behind a heavy
 * document ingest is still making progress, and reporting it as a failure
 * would be false. Only a FAILED revision, a request error, or the hard budget
 * ends the chain as a failure.
 */
const POLL_INTERVAL_MS = 2000;
const SOFT_POLL_ATTEMPTS = 20;
const HARD_POLL_ATTEMPTS = 300;

export type IngestItemStatus =
  | "pending"
  | "writing"
  | "queued"
  | "processing"
  | "active"
  | "failed";

export type IngestItemState = Readonly<{
  key: ProjectKnowledgeCategory;
  status: IngestItemStatus;
}>;

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
      /** Every category in the batch with its live status, in write order. */
      items: readonly IngestItemState[];
      /** The current category outlived the soft poll budget; still working. */
      slow?: boolean;
    }>
  | Readonly<{
      phase: "failed";
      failed: ProjectKnowledgeCategory;
      /** The backend's own words; an empty string when it gave none. */
      message: string;
      activated: readonly ProjectKnowledgeCategory[];
    }>
  | Readonly<{
      phase: "done";
      activated: readonly ProjectKnowledgeCategory[];
    }>;

export type ProjectIngest = Readonly<{
  state: IngestState;
  /**
   * Write every category in order, awaiting each one becoming active before
   * starting the next. Order is not cosmetic: a category that references
   * `job_ids` is rejected unless those jobs are already active, so `jobs` must
   * lead the batch.
   *
   * Resolves true only when the chain reached its done state — every write
   * active. A failure, the hard poll budget or a cancel resolves false: the
   * reason is reported through `state`, never a throw, so a caller that
   * continues past the chain must check this before treating the knowledge as
   * landed.
   *
   * With `sourceFile`, upload the file and plan once and observe the worker's
   * durable progress. Upload failure blocks the run. Without a source file,
   * replace categories directly and await exact active revision IDs.
   */
  ingest: (
    projectId: string,
    writes: readonly IngestWrite[],
    sourceFile?: File,
  ) => Promise<boolean>;
  /** Stop observing; a durable source upload continues on the worker. */
  cancel: () => void;
}>;

type WaitOutcome =
  | Readonly<{ ok: true }>
  | Readonly<{ ok: false; message: string }>;

/**
 * Uploads a brief and its grounded category plan once. The worker owns the
 * durable chain; this hook only observes progress, so leaving the page cannot
 * strand half a project. Manual category edits await exact revision activation.
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
  const pendingWaitRef = useRef<((outcome: WaitOutcome) => void) | null>(null);

  const cancel = useCallback(() => {
    epochRef.current += 1;
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    pendingWaitRef.current?.({ ok: false, message: "" });
    pendingWaitRef.current = null;
  }, []);

  useEffect(() => cancel, [cancel]);

  const waitForActive = useCallback(
    (
      projectId: string,
      category: ProjectKnowledgeCategory,
      revisionId: string,
      epoch: number,
      onStatus: (status: "queued" | "processing", slow: boolean) => void,
    ) =>
      new Promise<WaitOutcome>((resolve) => {
        const finish = (outcome: WaitOutcome) => {
          if (pendingWaitRef.current === finish) pendingWaitRef.current = null;
          resolve(outcome);
        };
        pendingWaitRef.current = finish;
        const attempt = (tries: number) => {
          timerRef.current = window.setTimeout(() => {
            timerRef.current = null;
            if (epoch !== epochRef.current) {
              finish({ ok: false, message: "" });
              return;
            }
            // A hidden tab must not keep hitting the backend; park the hop
            // without consuming budget rather than spinning in the background.
            if (document.visibilityState === "hidden") {
              attempt(tries);
              return;
            }
            void getProjectKnowledgeCategories(projectId)
              .then((catalog) => {
                if (epoch !== epochRef.current) {
                  finish({ ok: false, message: "" });
                  return;
                }
                const row = catalog.data.find(
                  (item) =>
                    item.key === category &&
                    item.active_revision_id === revisionId,
                );
                if (row) {
                  finish({ ok: true });
                  return;
                }
                const failed = catalog.data.find(
                  (item) =>
                    item.key === category &&
                    item.latest_revision_id === revisionId &&
                    item.status === "FAILED",
                );
                if (failed) {
                  finish({ ok: false, message: failed.error_message ?? "" });
                  return;
                }
                // Acceptance queues a revision; only an exact active revision
                // confirms it is searchable. A stale or missing catalog row
                // remains pending through the same bounded polling budget.
                const latest = catalog.data.find(
                  (item) =>
                    item.key === category &&
                    item.latest_revision_id === revisionId,
                );
                const status =
                  latest?.status === "PROCESSING" ? "processing" : "queued";
                // Past the soft budget the run is slow but alive; keep
                // polling. The board shows the category as still processing
                // instead of declaring a false failure.
                onStatus(status, tries >= SOFT_POLL_ATTEMPTS);
                if (tries < HARD_POLL_ATTEMPTS) {
                  attempt(tries + 1);
                  return;
                }
                finish({
                  ok: false,
                  message:
                    "Hệ thống xử lý chậm bất thường. Kiến thức vẫn đang được xử lý; thử nhập lại tệp sau ít phút.",
                });
                return;
              })
              .catch((error: unknown) => {
                if (epoch === epochRef.current) {
                  finish({ ok: false, message: (error as Error).message });
                } else {
                  finish({ ok: false, message: "" });
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
    ): Promise<boolean> => {
      cancel();
      const epoch = epochRef.current;
      const activated: ProjectKnowledgeCategory[] = [];
      if (writes.length === 0) {
        setState({
          phase: "failed",
          failed: "jobs",
          message:
            "Tệp chưa có nội dung kiến thức có thể nạp. Bổ sung thông tin tuyển dụng rồi tải lại tệp.",
          activated: [],
        });
        return false;
      }
      if (sourceFile) {
        const first = writes[0].key;
        setState({
          phase: "running",
          current: first,
          activated: [],
          total: writes.length,
          items: writes.map((write) => ({ key: write.key, status: "pending" })),
        });
        try {
          const receipt = await uploadProjectDocument(
            projectId,
            sourceFile,
            writes,
          );
          if (epoch !== epochRef.current) return false;
          const outcome = await new Promise<WaitOutcome>((resolve) => {
            const finish = (value: WaitOutcome) => {
              if (pendingWaitRef.current === finish)
                pendingWaitRef.current = null;
              resolve(value);
            };
            pendingWaitRef.current = finish;
            const poll = (tries: number, errors = 0) => {
              timerRef.current = window.setTimeout(() => {
                timerRef.current = null;
                if (epoch !== epochRef.current) {
                  finish({ ok: false, message: "" });
                  return;
                }
                if (document.visibilityState === "hidden") {
                  poll(tries, errors);
                  return;
                }
                void getProjectTrainingDocument(receipt.id)
                  .then((document) => {
                    if (epoch !== epochRef.current) {
                      finish({ ok: false, message: "" });
                      return;
                    }
                    const training = document.project_training;
                    const completed = training?.completed ?? [];
                    const current =
                      training?.current ??
                      writes.find((write) => !completed.includes(write.key))
                        ?.key ??
                      first;
                    activated.splice(
                      0,
                      activated.length,
                      ...writes
                        .filter((write) => completed.includes(write.key))
                        .map((write) => write.key),
                    );
                    if (
                      document.status === "FAILED" ||
                      document.status === "ARCHIVED" ||
                      training?.status === "FAILED"
                    ) {
                      setState({
                        phase: "failed",
                        failed: current,
                        message:
                          training?.error ||
                          document.error ||
                          "Không thể nạp tệp. Hãy kiểm tra nội dung rồi tải lại.",
                        activated: [...activated],
                      });
                      finish({ ok: false, message: "" });
                      return;
                    }
                    if (training?.status === "COMPLETED") {
                      if (activated.length !== writes.length) {
                        finish({
                          ok: false,
                          message:
                            "Hệ thống chưa xác nhận đầy đủ các danh mục. Hãy tải lại tệp.",
                        });
                        return;
                      }
                      finish({ ok: true });
                      return;
                    }
                    setState({
                      phase: "running",
                      current,
                      activated: [...activated],
                      total: writes.length,
                      slow: tries >= SOFT_POLL_ATTEMPTS,
                      items: writes.map((write) => ({
                        key: write.key,
                        status: completed.includes(write.key)
                          ? "active"
                          : training?.current === write.key
                            ? "processing"
                            : "queued",
                      })),
                    });
                    if (tries < HARD_POLL_ATTEMPTS) {
                      poll(tries + 1);
                      return;
                    }
                    finish({
                      ok: false,
                      message:
                        "Chưa nhận được kết quả xử lý. Tệp đã được lưu và hệ thống tiếp tục nạp; kiểm tra lại dự án sau ít phút.",
                    });
                  })
                  .catch((error: unknown) => {
                    if (epoch !== epochRef.current) {
                      finish({ ok: false, message: "" });
                      return;
                    }
                    if (errors < 2 && tries < HARD_POLL_ATTEMPTS) {
                      poll(tries + 1, errors + 1);
                      return;
                    }
                    finish({ ok: false, message: (error as Error).message });
                  });
              }, POLL_INTERVAL_MS);
            };
            poll(0);
          });
          if (epoch !== epochRef.current) return false;
          if (!outcome.ok) {
            // The worker failure above already preserves its exact category.
            if (outcome.message)
              setState({
                phase: "failed",
                failed:
                  writes.find((write) => !activated.includes(write.key))?.key ??
                  first,
                message: outcome.message,
                activated: [...activated],
              });
            return false;
          }
          setState({ phase: "done", activated: [...activated] });
          return true;
        } catch (error) {
          if (epoch !== epochRef.current) return false;
          setState({
            phase: "failed",
            failed: first,
            message: (error as Error).message,
            activated: [],
          });
          return false;
        }
      }
      const itemStates = writes.map(
        (write): IngestItemState => ({ key: write.key, status: "pending" }),
      );
      const setItem = (index: number, status: IngestItemStatus): void => {
        itemStates[index] = { ...itemStates[index], status };
      };

      for (const [index, write] of writes.entries()) {
        if (epoch !== epochRef.current) return false;
        setItem(index, "writing");
        setState({
          phase: "running",
          current: write.key,
          activated: [...activated],
          total: writes.length,
          items: itemStates.map((item) => ({ ...item })),
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
          if (epoch !== epochRef.current) return false;
          setItem(index, "failed");
          if (epoch !== epochRef.current) return false;
          setState({
            phase: "failed",
            failed: write.key,
            message: (error as Error).message,
            activated: [...activated],
          });
          return false;
        }

        if (epoch !== epochRef.current) return false;
        const outcome = await waitForActive(
          projectId,
          write.key,
          revisionId,
          epoch,
          (status, slow) => {
            setItem(index, status);
            setState({
              phase: "running",
              current: write.key,
              activated: [...activated],
              total: writes.length,
              items: itemStates.map((item) => ({ ...item })),
              slow,
            });
          },
        );
        if (epoch !== epochRef.current) return false;
        if (!outcome.ok) {
          setItem(index, "failed");
          if (epoch !== epochRef.current) return false;
          setState({
            phase: "failed",
            failed: write.key,
            message: outcome.message,
            activated: [...activated],
          });
          return false;
        }
        setItem(index, "active");
        activated.push(write.key);
      }

      if (epoch !== epochRef.current) return false;
      if (epoch !== epochRef.current) return false;
      setState({ phase: "done", activated: [...activated] });
      return true;
    },
    [cancel, waitForActive],
  );

  return { state, ingest, cancel };
};
