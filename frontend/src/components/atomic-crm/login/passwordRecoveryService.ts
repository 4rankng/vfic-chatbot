import { ApiError, apiUrl } from "@/lib/apiClient";

const publicJson = async (
  path: string,
  body: Record<string, unknown>,
): Promise<void> => {
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (response.ok) return;

  let detail: unknown;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    // ignore malformed error body
  }
  throw new ApiError(
    response.status,
    typeof detail === "string"
      ? detail
      : "Yêu cầu không hợp lệ, vui lòng kiểm tra lại.",
  );
};

export const requestPasswordResetOtp = async (email: string): Promise<void> => {
  await publicJson("/api/v1/auth/forgot-password", { email });
};

export const resetPasswordWithOtp = async (params: {
  email: string;
  otp: string;
  newPassword: string;
}): Promise<void> => {
  await publicJson("/api/v1/auth/reset-password", {
    email: params.email,
    otp: params.otp,
    new_password: params.newPassword,
  });
};
