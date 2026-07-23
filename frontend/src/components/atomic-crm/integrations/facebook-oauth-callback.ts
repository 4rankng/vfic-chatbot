const FACEBOOK_OAUTH_CALLBACK_KEYS = [
  "facebook_oauth_status",
  "facebook_oauth_flow_id",
  "facebook_oauth_error",
] as const;

const FACEBOOK_OAUTH_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  invalid_state:
    "Phiên kết nối không hợp lệ hoặc đã hết hạn. Vui lòng kết nối lại.",
  invalid_admin: "Tài khoản quản trị không còn hợp lệ. Vui lòng đăng nhập lại.",
  session_changed:
    "Phiên đăng nhập đã thay đổi. Vui lòng đăng nhập và kết nối lại.",
  missing_code: "Facebook không trả về mã ủy quyền. Vui lòng thử kết nối lại.",
  exchange_failed:
    "Không thể hoàn tất ủy quyền Facebook. Vui lòng thử kết nối lại.",
  no_pages: "Không tìm thấy Trang Facebook có thể kết nối.",
};

const GENERIC_OAUTH_ERROR =
  "Không thể hoàn tất kết nối Facebook. Vui lòng thử lại.";

export type FacebookOAuthCallback = {
  flowId: string | null;
  errorMessage: string | null;
  cleanHash: string;
};

export const consumeFacebookOAuthCallback = (
  hash: string,
): FacebookOAuthCallback | null => {
  const queryIndex = hash.indexOf("?");
  if (queryIndex === -1) return null;

  const hashPath = hash.slice(0, queryIndex);
  const params = new URLSearchParams(hash.slice(queryIndex + 1));
  if (!FACEBOOK_OAUTH_CALLBACK_KEYS.some((key) => params.has(key))) return null;

  const status = params.get("facebook_oauth_status");
  const callbackFlowId = params.get("facebook_oauth_flow_id")?.trim() ?? "";
  const errorCode = params.get("facebook_oauth_error") ?? "";

  FACEBOOK_OAUTH_CALLBACK_KEYS.forEach((key) => params.delete(key));
  const cleanQuery = params.toString();
  const cleanHash = cleanQuery ? `${hashPath}?${cleanQuery}` : hashPath;

  if (status === "pending_selection" && callbackFlowId) {
    return { flowId: callbackFlowId, errorMessage: null, cleanHash };
  }
  if (status === "error") {
    return {
      flowId: null,
      errorMessage:
        FACEBOOK_OAUTH_ERROR_MESSAGES[errorCode] ?? GENERIC_OAUTH_ERROR,
      cleanHash,
    };
  }
  return { flowId: null, errorMessage: GENERIC_OAUTH_ERROR, cleanHash };
};
