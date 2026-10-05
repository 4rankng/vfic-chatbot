import { PROJECT_KNOWLEDGE_CATEGORY_LABELS } from "../domain/project-knowledge-policy";
import type { IngestState } from "./use-project-ingest";

export type IngestCheckpointState = "done" | "active" | "pending" | "failed";

export type IngestCheckpointKey =
  | "file"
  | "draft"
  | "analyze"
  | "classify"
  | "finish";

export type IngestCheckpoint = Readonly<{
  key: IngestCheckpointKey;
  label: string;
  state: IngestCheckpointState;
  detail?: string;
}>;

export type IngestTimelineInput = Readonly<{
  /** The strip is still reading and parsing the picked file in the browser. */
  readingFile: boolean;
  /** The parent is inside the create-draft-then-ingest chain. */
  creatingDraft: boolean;
  /** Draft creation itself failed; the chain never reached the backend. */
  draftFailed: boolean;
  draftId: string | null;
  hasBrief: boolean;
  ingest: IngestState;
}>;

const SLOW_HINT = " — hệ thống đang bận, vẫn đang xử lý";

const label = (key: keyof typeof PROJECT_KNOWLEDGE_CATEGORY_LABELS) =>
  PROJECT_KNOWLEDGE_CATEGORY_LABELS[key];

/**
 * Derives the pipeline checkpoints from exactly what each layer has
 * confirmed: the browser read, the draft write, the backend's extraction
 * counts, and the catalog's per-category activations. Nothing shows as done
 * that the corresponding layer has not confirmed.
 */
export const buildIngestTimeline = ({
  readingFile,
  creatingDraft,
  draftFailed,
  draftId,
  hasBrief,
  ingest,
}: IngestTimelineInput): readonly IngestCheckpoint[] => {
  const running = ingest.phase === "running";
  const failed = ingest.phase === "failed";
  const done = ingest.phase === "done";

  const items = running ? ingest.items : [];
  const sections = running ? ingest.sections : undefined;
  const activated = ingest.phase === "idle" ? [] : [...ingest.activated];
  // A failure with a named category or confirmed activations happened while
  // classifying; otherwise it happened while uploading or extracting.
  const classifyEngaged =
    running || done || failed
      ? running
        ? items.length > 0
        : failed
          ? ingest.failed !== null || activated.length > 0
          : true
      : false;

  const checkpoints: IngestCheckpoint[] = [
    {
      key: "file",
      label: "Đọc tệp",
      state: readingFile
        ? "active"
        : hasBrief || draftId !== null
          ? "done"
          : "pending",
      detail: readingFile ? "Đang đọc và phân tích tệp đã chọn…" : undefined,
    },
    {
      key: "draft",
      label: "Tạo bản nháp dự án",
      state: draftFailed
        ? "failed"
        : draftId !== null
          ? "done"
          : creatingDraft && ingest.phase === "idle"
            ? "active"
            : "pending",
      detail:
        draftId === null && creatingDraft && ingest.phase === "idle"
          ? "Đang tạo bản nháp để nạp kiến thức…"
          : undefined,
    },
    {
      key: "analyze",
      label: "Phân tích nội dung tệp",
      state: failed
        ? classifyEngaged
          ? "done"
          : "failed"
        : done || (running && items.length > 0)
          ? "done"
          : running
            ? "active"
            : "pending",
      detail: running
        ? items.length === 0
          ? sections
            ? `Đang đọc cấu trúc tệp (${sections.completed}/${sections.total} đoạn)${ingest.slow ? SLOW_HINT : ""}…`
            : "Đang tải tệp lên hệ thống…"
          : undefined
        : undefined,
    },
    {
      key: "classify",
      label: "Phân loại vào 12 danh mục",
      state: failed
        ? classifyEngaged
          ? "failed"
          : "pending"
        : done
          ? "done"
          : running && items.length > 0
            ? "active"
            : "pending",
      detail: running
        ? items.length > 0
          ? ingest.current
            ? `Đang nạp «${label(ingest.current)}» (${items.findIndex((item) => item.key === ingest.current) + 1}/${ingest.total})${ingest.slow ? SLOW_HINT : ""}…`
            : `Đã xác nhận ${activated.length}/${ingest.total} danh mục…`
          : undefined
        : undefined,
    },
  ];

  if (done) {
    checkpoints.push({
      key: "finish",
      label: "Hoàn tất",
      state: "done",
      detail: ingest.requiresCutover
        ? `Đã chuẩn bị ${activated.length} phần kiến thức — chờ chuyển đổi trước khi chatbot sử dụng.`
        : `Đã nạp ${activated.length} danh mục kiến thức.`,
    });
  } else if (failed) {
    checkpoints.push({
      key: "finish",
      label: "Hoàn tất",
      state: "pending",
    });
  }

  return checkpoints;
};
