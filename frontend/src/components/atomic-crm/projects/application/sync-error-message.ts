const SYNC_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  missing_gid: "Link Google Sheet cần có gid để chọn đúng tab.",
  invalid_gid: "gid trong link không hợp lệ. Hãy sao chép lại link của đúng tab.",
  unsafe_gid: "gid trong link quá lớn. Hãy sao chép lại link trực tiếp từ Google Sheet.",
  conflicting_gid: "Link có nhiều gid khác nhau. Hãy giữ lại một gid cho tab cần đồng bộ.",
  invalid_sheet_id: "Không nhận diện được Google Sheet. Hãy kiểm tra lại link.",
  scheme_not_https: "Link Google Sheet phải bắt đầu bằng https://.",
  url_credentials_forbidden: "Link không được chứa thông tin đăng nhập.",
  invalid_url: "Link Google Sheet không hợp lệ. Hãy kiểm tra và thử lại.",
  ip_literal_forbidden: "Link này không được hỗ trợ. Hãy dùng link Google Sheet công khai.",
  host_not_allowed: "Chỉ hỗ trợ link Google Sheet công khai của Google.",
  dns_resolution_failed: "Chưa kết nối được Google Sheet. Vui lòng thử lại sau.",
  private_or_loopback_ip: "Link này không được hỗ trợ. Hãy dùng link Google Sheet công khai.",
  sheet_too_large: "Google Sheet quá lớn. Hãy rút gọn nội dung rồi đồng bộ lại.",
  fetch_failed: "Chưa tải được Google Sheet. Hãy kiểm tra quyền xem và thử lại.",
  unexpected_content_type: "Google Sheet chưa trả về dữ liệu bảng. Hãy kiểm tra link và quyền xem.",
  sheet_not_public: "Google Sheet chưa công khai. Hãy bật quyền xem cho bất kỳ ai có link.",
  empty_sheet: "Google Sheet chưa có câu hỏi và câu trả lời hợp lệ.",
  sheet_parse_failed: "Không đọc được dữ liệu trong Sheet. Hãy kiểm tra định dạng cột.",
  "parse_failed:csv_field_too_large": "Một ô trong Sheet quá dài. Hãy rút gọn nội dung rồi thử lại.",
  "direct_file_rejected:content_too_large": "Nội dung vượt giới hạn trang kiến thức. Hãy rút gọn Sheet.",
  direct_file_rejected: "Không thể thay thế trang kiến thức bằng dữ liệu này. Hãy kiểm tra nội dung.",
  direct_file_update_failed: "Chưa cập nhật được trang kiến thức. Nội dung cũ vẫn được giữ; hãy thử lại.",
  project_invalid: "Dự án không còn sẵn sàng để đồng bộ. Hãy làm mới trang và kiểm tra cấu hình.",
  "project_invalid:single_page_needs_discovery_card": "Hãy hoàn tất thẻ khám phá dự án trước khi đồng bộ.",
  single_page_external_source_already_exists: "Dự án đã có một nguồn Google Sheet. Hãy xóa nguồn cũ trước.",
  single_page_external_source_not_found: "Nguồn đồng bộ không còn tồn tại. Hãy làm mới danh sách.",
  run_now_cooldown: "Vui lòng đợi 5 phút giữa các lần xử lý.",
  single_page_sync_enqueue_failed: "Chưa thể bắt đầu đồng bộ. Vui lòng thử lại sau.",
  single_page_sync_enqueue_status_unknown: "Yêu cầu có thể đã được nhận. Hãy chờ và làm mới trạng thái trước khi thử lại.",
  state_not_found: "Nguồn đồng bộ không còn tồn tại. Hãy làm mới danh sách.",
  "This operation requires a single-page Project": "Thao tác này chỉ dùng cho dự án kiến thức một trang.",
};

export const singlePageSyncErrorMessage = (error: unknown): string => {
  const raw =
    typeof error === "string"
      ? error.trim()
      : error instanceof Error
        ? error.message.trim()
        : "";
  if (SYNC_ERROR_MESSAGES[raw]) return SYNC_ERROR_MESSAGES[raw];
  if (/^http_(401|403)$/.test(raw)) {
    return "Google Sheet chưa cho phép truy cập. Hãy bật quyền xem cho bất kỳ ai có link.";
  }
  if (/^http_404$/.test(raw)) {
    return "Không tìm thấy Google Sheet hoặc tab đã chọn. Hãy kiểm tra lại link.";
  }
  if (/^http_4\d\d$/.test(raw)) {
    return "Google Sheet từ chối yêu cầu. Hãy kiểm tra link và quyền xem.";
  }
  const status =
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    typeof error.status === "number"
      ? error.status
      : null;
  if (status === 403) return "Bạn không có quyền thực hiện thao tác này.";
  if (status === 404) return "Không tìm thấy nguồn đồng bộ. Hãy làm mới danh sách.";
  if (status === 409) {
    return "Không thể thực hiện do trạng thái hiện tại. Hãy làm mới và thử lại.";
  }
  if (status === 429) return "Vui lòng đợi 5 phút giữa các lần xử lý.";
  return "Chưa thể đồng bộ Google Sheet. Vui lòng kiểm tra link, quyền xem và thử lại.";
};
