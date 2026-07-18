import type {
  DecisionTraceDecisionEvent,
  DecisionTraceToolEvent,
} from "../types";

const DECISION_LABELS: Readonly<Record<string, string>> = Object.freeze({
  context_selected: "Đã chọn nguồn ngữ cảnh",
  degradation_reason: "Đã chuyển sang phương án suy giảm",
  grounding_verdict: "Đã kiểm tra căn cứ",
  lane_selected: "Đã chọn luồng xử lý",
  model_selected: "Đã chọn tầng mô hình",
  ownership_verdict: "Đã kiểm tra quyền trả lời",
  recovery_reason: "Đã phục hồi lần xử lý",
  required_tool_selected: "Đã chọn công cụ bắt buộc",
  route_selected: "Đã chọn hướng xử lý",
  safety_verdict: "Đã kiểm tra an toàn",
});

const SUMMARY_LABELS: Readonly<Record<string, string>> = Object.freeze({
  agent: "Luồng tác nhân",
  agent_graph: "Ngữ cảnh từ luồng tác nhân",
  blocklist_redirect: "Chuyển hướng do danh sách chặn",
  claimed: "Chatbot đã giành quyền trả lời",
  contact_terms: "Câu hỏi về thông tin liên hệ",
  direct: "Trả lời trực tiếp",
  direct_context: "Ngữ cảnh trả lời trực tiếp",
  empty: "Nội dung trống",
  empty_after_clean: "Nội dung trống sau khi làm sạch",
  fallback: "Hướng xử lý dự phòng",
  faq_bypass: "Ngữ cảnh hỏi đáp nhanh",
  fast: "Mô hình nhanh",
  fast_lane_match: "Khớp luồng xử lý nhanh",
  focused_rag: "Ngữ cảnh truy xuất tập trung",
  get_product_features: "Tra cứu đặc điểm dự án",
  grounded: "Có căn cứ",
  internal_retry_prompt: "Yêu cầu thử lại nội bộ",
  job_detail_terms: "Câu hỏi chi tiết việc làm",
  list_active_jobs: "Liệt kê việc làm đang tuyển",
  list_active_projects: "Liệt kê dự án đang hoạt động",
  llm_throttled: "Giới hạn tải mô hình",
  off_domain_terms: "Nội dung ngoài phạm vi",
  outbox_recovery: "Phục hồi từ hàng đợi gửi",
  passed: "Đạt kiểm tra an toàn",
  phone_number: "Phát hiện số điện thoại",
  primary: "Mô hình chính",
  profile_terms: "Câu hỏi về hồ sơ",
  project_clarification: "Làm rõ dự án",
  recommendation_terms: "Yêu cầu gợi ý việc làm",
  recommend_jobs: "Gợi ý việc làm",
  recommend_projects: "Gợi ý dự án",
  risk_redirect: "Chuyển hướng do rủi ro",
  sanitized: "Đã làm sạch theo căn cứ",
  search_bus_timetable: "Tra cứu lịch xe",
  search_knowledge: "Tra cứu cơ sở kiến thức",
  search_user_memory: "Tra cứu thông tin đã ghi nhận",
  skipped: "Không cần kiểm tra căn cứ",
  suppressed: "Đã chặn gửi",
  timetable_terms: "Câu hỏi về lịch xe",
  truncated: "Nội dung đã được rút gọn an toàn",
  vacancy_listing: "Yêu cầu danh sách việc làm",
  vacancy_terms: "Câu hỏi về việc đang tuyển",
});

const TOOL_LABELS: Readonly<Record<string, string>> = Object.freeze({
  get_product_features: "Tra cứu đặc điểm dự án",
  list_active_jobs: "Liệt kê việc làm đang tuyển",
  list_active_projects: "Liệt kê dự án đang hoạt động",
  recommend_jobs: "Gợi ý việc làm",
  recommend_projects: "Gợi ý dự án",
  search_bus_timetable: "Tra cứu lịch xe",
  search_knowledge: "Tra cứu cơ sở kiến thức",
  search_user_memory: "Tra cứu thông tin đã ghi nhận",
});

const SELECTION_SOURCE_LABELS: Readonly<
  Record<DecisionTraceToolEvent["selected_by"], string>
> = Object.freeze({
  model: "mô hình",
  policy: "chính sách",
  prefetch: "tải trước",
});

export const decisionEventLabels = (
  event: DecisionTraceDecisionEvent,
): { title: string; detail: string } => ({
  title: DECISION_LABELS[event.code] ?? "Quyết định chưa được hỗ trợ",
  detail: SUMMARY_LABELS[event.summary_code] ?? "Giá trị chưa được hỗ trợ",
});

export const toolEventLabels = (
  event: DecisionTraceToolEvent,
): { title: string; detail: string } => ({
  title: TOOL_LABELS[event.name] ?? "Công cụ chưa được hỗ trợ",
  detail: `Được chọn bởi ${SELECTION_SOURCE_LABELS[event.selected_by]}`,
});
