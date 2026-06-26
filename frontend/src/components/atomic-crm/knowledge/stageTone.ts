// Tailwind tone classes for the training-pipeline `stage` of a knowledge document.
// Unknown values fall back to muted.
export const stageTone = (stage?: string | null, status?: string): string => {
  const s = (status ?? stage ?? "").toUpperCase();
  if (s === "APPROVED") return "bg-emerald-500 text-white";
  if (s === "READY_FOR_REVIEW") return "bg-amber-500 text-white";
  if (s === "FAILED") return "bg-rose-500 text-white";
  if (
    s === "DIGESTING" ||
    s === "EMBEDDING" ||
    s === "INDEXING" ||
    s === "PROCESSING"
  )
    return "bg-sky-500 text-white";
  return "bg-muted text-muted-foreground";
};

// Vietnamese label for a pipeline stage.
export const stageLabel = (stage?: string | null): string => {
  switch ((stage ?? "").toUpperCase()) {
    case "UPLOADED":
      return "Đã tải lên";
    case "EXTRACTED":
      return "Đã trích văn bản";
    case "DIGESTING":
      return "Đang phân tích (LLM)";
    case "EMBEDDING":
      return "Đang nhúng vector";
    case "INDEXING":
      return "Đang lập chỉ mục";
    case "READY_FOR_REVIEW":
      return "Chờ duyệt";
    case "APPROVED":
      return "Đã duyệt";
    case "FAILED":
      return "Lỗi";
    case "REJECTED":
      return "Đã từ chối";
    case "ARCHIVED":
      return "Đã lưu trữ";
    default:
      return stage ?? "—";
  }
};
