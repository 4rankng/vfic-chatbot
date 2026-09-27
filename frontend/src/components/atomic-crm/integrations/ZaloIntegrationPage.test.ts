import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiJson: vi.fn(() => Promise.resolve({ accounts: [] })),
}));

vi.mock("@/lib/apiClient", () => ({ apiJson: mocks.apiJson }));

import { zaloIntegrationGateway } from "./api";
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

describe("zalo OA account gateway", () => {
  beforeEach(() => {
    mocks.apiJson.mockClear();
  });

  it("lists linked OAs from the collection endpoint", async () => {
    await zaloIntegrationGateway.listZaloOaAccounts();

    expect(mocks.apiJson.mock.calls[0]).toEqual([
      "/api/v1/admin/integrations/zalo/oa-accounts",
    ]);
  });

  it("links an OA with a POST to the collection endpoint", async () => {
    const body = {
      oa_id: "123456789",
      label: "OA Tuyển dụng",
      access_token: "access-token",
    };

    await zaloIntegrationGateway.linkZaloOaAccount(body);

    expect(mocks.apiJson.mock.calls[0]).toEqual([
      "/api/v1/admin/integrations/zalo/oa-accounts",
      { method: "POST", body },
    ]);
  });

  it("unlinks an OA with the account key URL-encoded", async () => {
    await zaloIntegrationGateway.unlinkZaloOaAccount("default:zalo oa/1");

    expect(mocks.apiJson.mock.calls[0]).toEqual([
      "/api/v1/admin/integrations/zalo/oa-accounts/default%3Azalo%20oa%2F1",
      { method: "DELETE" },
    ]);
  });
});
