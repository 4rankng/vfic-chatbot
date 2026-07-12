import { describe, expect, it } from "vitest";

import { buildZaloUpdatePayload } from "./zaloUpdatePayload";

const draft = {
  zalo_bot_token: "bot-token-that-must-not-be-sent",
  zalo_bot_webhook_secret: "bot-webhook-secret",
  zalo_oa_app_id: "oa-app-id",
  zalo_oa_secret_key: "oa-webhook-secret",
  zalo_oa_access_token: "new-oa-access-token",
  zalo_oa_refresh_token: "new-oa-refresh-token",
};

describe("buildZaloUpdatePayload", () => {
  it("limits an OA save to OA credentials when bot fields contain stale values", () => {
    expect(buildZaloUpdatePayload(draft, "oa-app-id", "oa")).toEqual({
      zalo_oa_secret_key: "oa-webhook-secret",
      zalo_oa_access_token: "new-oa-access-token",
      zalo_oa_refresh_token: "new-oa-refresh-token",
    });
  });

  it("limits a bot save to bot credentials when OA fields contain values", () => {
    expect(buildZaloUpdatePayload(draft, "other-oa-app-id", "bot")).toEqual({
      zalo_bot_token: "bot-token-that-must-not-be-sent",
      zalo_bot_webhook_secret: "bot-webhook-secret",
    });
  });
});
