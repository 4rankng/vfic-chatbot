import { apiJson } from "@/lib/apiClient";

/**
 * Browser Web Push plumbing for the console bell.
 *
 * The server owns the alert decisions (see
 * `backend/app/services/push/service.py`); this module only registers the
 * browser with the deployment's VAPID key and reports what the browser said.
 * Every failure is surfaced as a Vietnamese message rather than thrown at a
 * component, because all of them are recoverable by the operator (permission,
 * unsupported browser, no keys on the server).
 */

export class PushError extends Error {}

const KEY_URL = "/api/v1/notifications/vapid-public-key";
const SUBSCRIPTION_URL = "/api/v1/notifications/subscriptions";
const TEST_URL = "/api/v1/notifications/test";

type VapidKeyResponse = { enabled: boolean; key: string };

/** The current browser can carry push at all. */
export const pushSupported = (): boolean =>
  typeof window !== "undefined" &&
  "serviceWorker" in navigator &&
  "PushManager" in window &&
  "Notification" in window;

/** `applicationServerKey` takes raw bytes; the server hands out base64url. */
const urlBase64ToUint8Array = (value: string): Uint8Array => {
  const padded = value.padEnd(
    value.length + ((4 - (value.length % 4)) % 4),
    "=",
  );
  const normalized = padded.replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(normalized);
  const bytes = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) {
    bytes[index] = raw.charCodeAt(index);
  }
  return bytes;
};

/** The deployment's public key, or null when the server has no VAPID pair. */
export const fetchVapidKey = async (): Promise<string | null> => {
  const response = await apiJson<VapidKeyResponse>(KEY_URL);
  return response.enabled && response.key ? response.key : null;
};

const registration = async (): Promise<ServiceWorkerRegistration> => {
  const ready = await navigator.serviceWorker.ready;
  if (!ready)
    throw new PushError("Trình duyệt chưa sẵn sàng cho thông báo đẩy.");
  return ready;
};

/** Whether this browser already holds a subscription. */
export const currentSubscription =
  async (): Promise<PushSubscription | null> => {
    if (!pushSupported()) return null;
    const ready = await registration();
    return ready.pushManager.getSubscription();
  };

/**
 * Ask for permission, subscribe, and store the subscription.
 *
 * A key rotation on the server leaves a browser subscribed with the old key:
 * the push service then rejects every send, so the existing subscription is
 * dropped and recreated whenever the stored key differs from the server's.
 */
export const enablePush = async (): Promise<void> => {
  if (!pushSupported()) {
    throw new PushError("Trình duyệt này không hỗ trợ thông báo đẩy.");
  }
  const serverKey = await fetchVapidKey();
  if (!serverKey) {
    throw new PushError("Máy chủ chưa cấu hình thông báo đẩy (VAPID).");
  }
  if (Notification.permission === "denied") {
    throw new PushError(
      "Trình duyệt đã chặn thông báo. Hãy bật lại trong cài đặt trang web.",
    );
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new PushError("Bạn chưa cho phép hiển thị thông báo.");
  }
  const ready = await registration();
  const existing = await ready.pushManager.getSubscription();
  if (existing) {
    // A subscription is bound to the VAPID key it was created with, and browsers
    // do not reliably expose that key for comparison (`options.applicationServerKey`
    // is null in some versions). Re-creating it is the only way to be sure the
    // server's current pair signs it — a mismatched pair fails every send with a
    // 403 the push service never reports as "gone", so it would never self-heal.
    await existing.unsubscribe();
  }
  const subscription = await ready.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(serverKey) as BufferSource,
  });
  await apiJson(SUBSCRIPTION_URL, {
    method: "POST",
    body: {
      endpoint: subscription.endpoint,
      keys: {
        p256dh: subscription.toJSON().keys?.p256dh ?? "",
        auth: subscription.toJSON().keys?.auth ?? "",
      },
      user_agent: navigator.userAgent.slice(0, 300),
    },
  });
};

/** Forget this browser locally and on the server. */
export const disablePush = async (): Promise<void> => {
  if (!pushSupported()) return;
  const existing = await currentSubscription();
  if (!existing) return;
  await existing.unsubscribe();
  await apiJson(SUBSCRIPTION_URL, {
    method: "DELETE",
    body: { endpoint: existing.endpoint },
  });
};

/** Send one push to this browser, so the toggle can prove itself. */
export const sendTestPush = async (): Promise<boolean> => {
  const response = await apiJson<{ sent: number }>(TEST_URL, {
    method: "POST",
  });
  return response.sent > 0;
};
