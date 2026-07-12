export type ZaloFormState = {
  zalo_bot_token: string;
  zalo_bot_webhook_secret: string;
  zalo_oa_app_id: string;
  zalo_oa_secret_key: string;
  zalo_oa_access_token: string;
  zalo_oa_refresh_token: string;
};

export type ZaloSettingsScope = "all" | "bot" | "oa";

const ZALO_BOT_FORM_KEYS = [
  "zalo_bot_token",
  "zalo_bot_webhook_secret",
] as const satisfies readonly (keyof ZaloFormState)[];

const ZALO_OA_FORM_KEYS = [
  "zalo_oa_app_id",
  "zalo_oa_secret_key",
  "zalo_oa_access_token",
  "zalo_oa_refresh_token",
] as const satisfies readonly (keyof ZaloFormState)[];

export const buildZaloUpdatePayload = (
  form: ZaloFormState,
  oaAppId: string | null | undefined,
  scope: ZaloSettingsScope = "all",
): Partial<ZaloFormState> => {
  const keys =
    scope === "bot"
      ? ZALO_BOT_FORM_KEYS
      : scope === "oa"
        ? ZALO_OA_FORM_KEYS
        : [...ZALO_BOT_FORM_KEYS, ...ZALO_OA_FORM_KEYS];
  const payload: Partial<ZaloFormState> = {};

  for (const key of keys) {
    const value = form[key].trim();
    if (!value || (key === "zalo_oa_app_id" && value === oaAppId)) continue;
    payload[key] = value;
  }
  return payload;
};
