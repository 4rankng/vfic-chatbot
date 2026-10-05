import { afterEach, describe, expect, it, vi } from "vitest";

const apiJson = vi.hoisted(() => vi.fn());
vi.mock(import("@/lib/apiClient"), () => ({ apiJson }));

import {
  PushError,
  currentSubscription,
  disablePush,
  enablePush,
  fetchVapidKey,
  sendTestPush,
} from "./pushNotifications";

const KEY =
  "BOngYWyxiJ7JWSfiBldHOmM4wlEeZHvyR_TqenUp3EyFusxovLtVLnmDcfZEuDjWeJlMk6hunCodLYkmW3di7e4";

type FakeSubscription = PushSubscription & {
  options?: { applicationServerKey?: ArrayBuffer };
};

const fakeSubscription = (
  endpoint = "https://push.test/abc",
  serverKey: string | null = KEY,
): FakeSubscription => {
  const record = {
    endpoint,
    toJSON: () => ({
      endpoint,
      keys: { p256dh: "p256dh-value", auth: "auth-value" },
    }),
    unsubscribe: vi.fn(async () => true),
  } as unknown as FakeSubscription;
  if (serverKey) {
    const bytes = Uint8Array.from(
      atob(serverKey.replace(/-/g, "+").replace(/_/g, "/")),
      (char) => char.charCodeAt(0),
    );
    Object.assign(record, { options: { applicationServerKey: bytes.buffer } });
  }
  return record;
};

const stubBrowser = (
  existing: FakeSubscription | null,
  permission = "granted",
) => {
  const subscribe = vi.fn(async () => existing ?? fakeSubscription());
  const registration = {
    pushManager: { getSubscription: vi.fn(async () => existing), subscribe },
  };
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: { ready: Promise.resolve(registration) },
  });
  vi.stubGlobal("Notification", {
    permission,
    requestPermission: vi.fn(async () => permission),
  });
  return { subscribe };
};

afterEach(() => {
  apiJson.mockReset();
  vi.unstubAllGlobals();
  // @ts-expect-error restoring the real descriptor between cases
  delete navigator.serviceWorker;
});

describe("pushNotifications", () => {
  it("reports the deployment's key, and null when push is not configured", async () => {
    apiJson.mockResolvedValueOnce({ enabled: true, key: KEY });
    expect(await fetchVapidKey()).toBe(KEY);

    apiJson.mockResolvedValueOnce({ enabled: false, key: "" });
    expect(await fetchVapidKey()).toBeNull();
  });

  it("subscribes the browser and stores the endpoint with its keys", async () => {
    apiJson
      .mockResolvedValueOnce({ enabled: true, key: KEY })
      .mockResolvedValueOnce(undefined);
    const { subscribe } = stubBrowser(null);

    await enablePush();

    expect(subscribe).toHaveBeenCalledOnce();
    expect(apiJson).toHaveBeenLastCalledWith(
      "/api/v1/notifications/subscriptions",
      expect.objectContaining({
        method: "POST",
        body: expect.objectContaining({
          endpoint: "https://push.test/abc",
          keys: { p256dh: "p256dh-value", auth: "auth-value" },
        }),
      }),
    );
  });

  it("re-creates the subscription so the server's current key signs it", async () => {
    // Chrome leaves `options.applicationServerKey` null, so the stored key cannot
    // be compared — the browser-side subscription is recreated instead, which is
    // also what repairs a subscription made before a VAPID rotation.
    const stale = fakeSubscription("https://push.test/stale", null);
    apiJson
      .mockResolvedValueOnce({ enabled: true, key: KEY })
      .mockResolvedValueOnce(undefined);
    const { subscribe } = stubBrowser(stale);

    await enablePush();

    expect(stale.unsubscribe).toHaveBeenCalledOnce();
    expect(subscribe).toHaveBeenCalledOnce();
  });

  it("refuses to subscribe when the server has no VAPID pair", async () => {
    apiJson.mockResolvedValueOnce({ enabled: false, key: "" });
    stubBrowser(null);

    await expect(enablePush()).rejects.toBeInstanceOf(PushError);
    expect(apiJson).toHaveBeenCalledTimes(1);
  });

  it("reports a denied permission instead of subscribing", async () => {
    apiJson.mockResolvedValueOnce({ enabled: true, key: KEY });
    stubBrowser(null, "denied");

    await expect(enablePush()).rejects.toThrow(/đã chặn thông báo/);
  });

  it("unsubscribes locally and on the server", async () => {
    const existing = fakeSubscription();
    apiJson.mockResolvedValueOnce(undefined);
    stubBrowser(existing);

    expect(await currentSubscription()).toBe(existing);
    await disablePush();

    expect(existing.unsubscribe).toHaveBeenCalledOnce();
    expect(apiJson).toHaveBeenLastCalledWith(
      "/api/v1/notifications/subscriptions",
      expect.objectContaining({
        method: "DELETE",
        body: { endpoint: "https://push.test/abc" },
      }),
    );
  });

  it("reports whether the self-test reached the browser", async () => {
    apiJson.mockResolvedValueOnce({ sent: 1 });
    expect(await sendTestPush()).toBe(true);

    apiJson.mockResolvedValueOnce({ sent: 0 });
    expect(await sendTestPush()).toBe(false);
  });
});
