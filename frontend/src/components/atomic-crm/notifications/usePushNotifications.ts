import { useCallback, useEffect, useState } from "react";

import {
  PushError,
  currentSubscription,
  disablePush,
  enablePush,
  pushSupported,
  sendTestPush,
} from "./pushNotifications";

/**
 * The console's push toggle state (bell panel).
 *
 * Whatever the browser holds is the truth: the panel mounts, asks the page
 * whether a subscription exists, and reports it. The server's own view is only
 * written through {@link enable} / {@link disable}, so a browser that was
 * unsubscribed elsewhere (or whose keys were rotated) shows as "off" instead of
 * claiming to be subscribed to a channel that no longer delivers.
 */
export type PushNotificationsState = {
  supported: boolean;
  subscribed: boolean;
  busy: boolean;
  error: string | null;
  sent: boolean;
  enable: () => Promise<void>;
  disable: () => Promise<void>;
  test: () => Promise<void>;
};

export const usePushNotifications = (): PushNotificationsState => {
  const [subscribed, setSubscribed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const supported = pushSupported();

  useEffect(() => {
    if (!supported) return;
    let cancelled = false;
    void currentSubscription()
      .then((subscription) => {
        if (!cancelled) setSubscribed(Boolean(subscription));
      })
      .catch(() => {
        if (!cancelled) setSubscribed(false);
      });
    return () => {
      cancelled = true;
    };
  }, [supported]);

  const run = useCallback(async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (cause) {
      setError(
        cause instanceof PushError
          ? cause.message
          : "Không thay đổi được thông báo đẩy. Vui lòng thử lại.",
      );
    } finally {
      setBusy(false);
    }
  }, []);

  const enable = useCallback(
    () =>
      run(async () => {
        await enablePush();
        setSubscribed(true);
      }),
    [run],
  );

  const disable = useCallback(
    () =>
      run(async () => {
        await disablePush();
        setSubscribed(false);
        setSent(false);
      }),
    [run],
  );

  const test = useCallback(
    () =>
      run(async () => {
        setSent(await sendTestPush());
      }),
    [run],
  );

  return { supported, subscribed, busy, error, sent, enable, disable, test };
};
