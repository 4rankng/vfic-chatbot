// Pure pipeline-stage classification helpers for knowledge sources.
//
// These have no React dependency and are shared across the knowledge-source
// list, row, detail panel, status stamps, and timeline. Extracted from
// KnowledgeSourceList.tsx so every "is this source published / failed /
// processing / stuck?" decision lives in one place.

import type { KnowledgeSource } from "../types";

export const PIPELINE_STEPS = [
  {
    key: "UPLOADED",
    label: "Đã nhận tệp",
    description: "File đã vào hệ thống và chờ trích văn bản.",
  },
  {
    key: "EXTRACTED",
    label: "Trích văn bản",
    description: "Nội dung đã được đọc từ PDF, Office, CSV hoặc TXT.",
  },
  {
    key: "DIGESTING",
    label: "Digest",
    description: "LLM đang tóm tắt, chia đơn vị và gắn cờ nội dung cần xem.",
  },
  {
    key: "EMBEDDING",
    label: "Vector",
    description: "Các đơn vị kiến thức đang được nhúng để tìm kiếm ngữ nghĩa.",
  },
  {
    key: "INDEXING",
    label: "Lập chỉ mục",
    description: "Nguồn đang được ghi vào kho truy xuất của agent.",
  },
  {
    key: "PUBLISHED",
    label: "Sẵn sàng",
    description: "Agent có thể dùng nguồn này để trả lời.",
  },
] as const;

export const flaggedCount = (source: KnowledgeSource): number =>
  source.digest_meta?.flagged_unit_indexes?.length ?? 0;

export const isCanonicalSource = (source: KnowledgeSource): boolean =>
  source.is_canonical === true;

export const sourceStage = (source: KnowledgeSource) =>
  source.stage ?? source.status ?? "UNKNOWN";

export const isPublished = (source: KnowledgeSource) =>
  ["PUBLISHED", "READY"].includes(sourceStage(source).toUpperCase()) ||
  ["published", "ready"].includes(source.status?.toLowerCase());

export const isFailed = (source: KnowledgeSource) =>
  ["FAILED", "ERROR"].includes(sourceStage(source).toUpperCase()) ||
  ["failed", "error"].includes(source.status?.toLowerCase());

export const isRunning = (source: KnowledgeSource) =>
  ["DIGESTING", "EMBEDDING", "INDEXING", "PROCESSING"].includes(
    sourceStage(source).toUpperCase(),
  );

export const isPipelineActive = (source: KnowledgeSource) =>
  [
    "UPLOADED",
    "EXTRACTED",
    "DIGESTING",
    "EMBEDDING",
    "INDEXING",
    "PROCESSING",
  ].includes(sourceStage(source).toUpperCase());

export const isWaitingForWorker = (source: KnowledgeSource) =>
  ["UPLOADED", "EXTRACTED"].includes(sourceStage(source).toUpperCase());

export const needsReview = (source: KnowledgeSource) =>
  flaggedCount(source) > 0 || isFailed(source);

export const sourceSearchText = (
  source: KnowledgeSource,
  projectName?: string,
) =>
  [
    source.file_name,
    source.source,
    source.mime_type,
    source.digest_summary,
    sourceStage(source),
    projectName,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

export const pipelineStepIndex = (source: KnowledgeSource) => {
  const stage = sourceStage(source).toUpperCase();
  if (stage === "READY") return PIPELINE_STEPS.length - 1;
  if (stage === "PROCESSING") return 2;
  const index = PIPELINE_STEPS.findIndex((step) => step.key === stage);
  return index >= 0 ? index : 0;
};

export const pipelinePercent = (source: KnowledgeSource) => {
  if (isFailed(source)) return 100;
  if (isPublished(source)) return 100;
  return Math.max(
    12,
    Math.round((pipelineStepIndex(source) / (PIPELINE_STEPS.length - 1)) * 100),
  );
};

export const pipelineStepCopy = (
  source: KnowledgeSource,
  step: (typeof PIPELINE_STEPS)[number],
) => {
  if (step.key !== "DIGESTING" || !isCanonicalSource(source)) return step;
  return {
    ...step,
    label: "Chuẩn hóa",
    description:
      "Markdown canonical đang được kiểm tra, sửa lỗi định dạng an toàn và chia đơn vị truy xuất.",
  };
};

export const pipelineStateCopy = (source: KnowledgeSource) => {
  if (isFailed(source)) {
    return "Pipeline dừng vì lỗi. Hãy huấn luyện lại sau khi kiểm tra định dạng hoặc nội dung nguồn.";
  }
  if (isPublished(source)) {
    return "Nguồn đã được xuất bản và agent có thể truy xuất khi trả lời.";
  }
  if (needsReview(source)) {
    return "Nguồn đã chạy xong nhưng có nội dung cần rà soát trước khi tin cậy hoàn toàn.";
  }
  if (isWaitingForWorker(source)) {
    return "Nguồn đã trích văn bản và đang chờ worker ingest nhận việc. Nếu đứng ở đây lâu, hãy kiểm tra tiến trình rq worker ingest.";
  }
  const current = pipelineStepCopy(source, PIPELINE_STEPS[pipelineStepIndex(source)]);
  return current?.description ?? "Nguồn đang được xử lý trong pipeline.";
};

export const minutesSinceUpdate = (source: KnowledgeSource) => {
  const time = new Date(source.updated_at ?? source.created_at).getTime();
  if (Number.isNaN(time)) return 0;
  return Math.max(0, Math.floor((Date.now() - time) / 60000));
};

export const isPossiblyStuck = (source: KnowledgeSource) =>
  isWaitingForWorker(source) && minutesSinceUpdate(source) >= 2;

export const isProcessing = (source: KnowledgeSource) =>
  isPipelineActive(source) && !isFailed(source);
