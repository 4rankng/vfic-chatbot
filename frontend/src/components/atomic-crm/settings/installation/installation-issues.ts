import type { InstallationIssue } from "../../installation/installation-client";

const ISSUE_MESSAGES: Record<string, string> = {
  SETUP_SECTION_REQUIRED: "Mục thiết lập này chưa hoàn tất.",
  PACK_SELECTION_INVALID: "Gói ngành hoặc chức năng đã chọn không hợp lệ.",
  TERMINOLOGY_KEY_INVALID: "Bộ thuật ngữ không phù hợp với gói ngành đã chọn.",
  TERMINOLOGY_REQUIRED: "Chưa nhập đủ thuật ngữ bắt buộc của gói ngành.",
  WORKFLOW_INVALID: "Quy trình không được gói ngành này hỗ trợ.",
  INTEGRATION_REFERENCE_INVALID: "Tích hợp đã chọn không được hỗ trợ.",
  INTEGRATION_REQUIRED_BY_CAPABILITY: "Chức năng đã chọn còn thiếu tích hợp bắt buộc.",
  TEMPLATE_REQUIRED_BY_CAPABILITY: "Chức năng kiến thức cần ít nhất một mẫu đã xuất bản.",
  PERSONA_CHECKSUM_MISMATCH: "Phiên bản Agent đã thay đổi. Vui lòng chọn lại.",
  PLAINTEXT_SECRET_FORBIDDEN: "Không được lưu khóa bí mật trong bản nháp.",
  STALE_LOCK_VERSION: "Bản nháp đã được người khác cập nhật.",
};

export const describeInstallationIssue = (issue: InstallationIssue): string =>
  ISSUE_MESSAGES[issue.code] ?? "Máy chủ phát hiện một mục cấu hình chưa hợp lệ.";
