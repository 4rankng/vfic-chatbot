// Pure form policy for the per-project external API panel.
//
// Deterministic and side-effect free, mirroring the backend rules so the admin
// sees the same objection inline instead of a 400 round trip. URLs are parsed
// with `URL` (not a regex) so the scheme/host verdicts match the server's
// `normalize_base_url`.

import type {
  ExternalApiFormState,
  ExternalApiUpdatePayload,
  ExternalApiView,
} from "./external-api-contracts";

export const EXTERNAL_API_MAX_GUIDE_CHARS = 16000;
export const EXTERNAL_API_MIN_GUIDE_CHARS = 20;

// Plain http is accepted only for these hosts (backend: EXTERNAL_API_LOCAL_HOSTS).
const LOOPBACK_HOSTS: Record<string, true> = {
  "127.0.0.1": true,
  localhost: true,
  "::1": true,
};

export const emptyExternalApiForm = (): ExternalApiFormState => ({
  enabled: false,
  base_url: "",
  auth_header: "X-API-Key",
  auth_scheme: "",
  guide: "",
  api_key: "",
  clear_api_key: false,
});

/** Seed the draft from the server view; the key field always starts blank. */
export const formFromView = (view: ExternalApiView): ExternalApiFormState => ({
  enabled: view.enabled,
  base_url: view.base_url,
  auth_header: view.auth_header,
  auth_scheme: view.auth_scheme,
  guide: view.guide,
  api_key: "",
  clear_api_key: false,
});

/**
 * Build the PUT body. A blank key field keeps the stored secret alive; only the
 * explicit clear action sends ``""``.
 */
export const buildExternalApiPayload = (
  form: ExternalApiFormState,
): ExternalApiUpdatePayload => {
  const payload: ExternalApiUpdatePayload = {
    enabled: form.enabled,
    base_url: form.base_url.trim(),
    auth_header: form.auth_header.trim(),
    auth_scheme: form.auth_scheme.trim(),
    guide: form.guide,
  };
  if (form.clear_api_key) return { ...payload, api_key: "" };
  const key = form.api_key.trim();
  return key ? { ...payload, api_key: key } : payload;
};

const invalidBaseUrl = (value: string): string | null => {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return "Base URL phải là một địa chỉ tuyệt đối, ví dụ https://api.example.com.";
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    return "Base URL chỉ hỗ trợ http hoặc https.";
  }
  if (parsed.username || parsed.password) {
    return "Base URL không được chứa thông tin đăng nhập.";
  }
  if (parsed.search || parsed.hash) {
    return "Base URL không được chứa query hoặc fragment.";
  }
  const host = parsed.hostname.toLowerCase();
  if (!host) return "Base URL thiếu tên miền.";
  if (parsed.protocol === "http:" && !(host in LOOPBACK_HOSTS)) {
    return "Chỉ dùng http cho 127.0.0.1/localhost; còn lại phải là https.";
  }
  return null;
};

/** Every objection the admin must resolve before the form may be saved. */
export const validateExternalApiForm = (form: ExternalApiFormState): string[] => {
  const errors: string[] = [];
  const baseUrl = form.base_url.trim();
  const guide = form.guide.trim();
  if (form.enabled && !baseUrl) {
    errors.push("Bật tích hợp cần nhập Base URL.");
  } else if (baseUrl) {
    const problem = invalidBaseUrl(baseUrl);
    if (problem) errors.push(problem);
  }
  if (form.enabled && guide.length < EXTERNAL_API_MIN_GUIDE_CHARS) {
    errors.push("Bật tích hợp cần dán hoặc tải lên hướng dẫn API.");
  }
  if (form.guide.length > EXTERNAL_API_MAX_GUIDE_CHARS) {
    errors.push(
      `Hướng dẫn API tối đa ${EXTERNAL_API_MAX_GUIDE_CHARS} ký tự (hiện ${form.guide.length}).`,
    );
  }
  return errors;
};
