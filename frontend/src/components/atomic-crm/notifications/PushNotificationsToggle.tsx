import { BellRinging01, BellOff01, Check } from "@untitledui/icons";

import { Button } from "@/components/base/buttons/button";
import { usePushNotifications } from "./usePushNotifications";

/**
 * Push on/off + a self-test, inside the bell panel.
 *
 * Lives here rather than in Settings because this is the surface an operator
 * opens when they wonder whether alerts reach them, and the answer has to be
 * one click away from the question. The self-test exists because a stored
 * subscription that never delivers (blocked permission, rotated keys) is
 * otherwise indistinguishable from having nothing to alert about.
 */
export const PushNotificationsToggle = () => {
  const { supported, subscribed, busy, error, sent, enable, disable, test } =
    usePushNotifications();

  if (!supported) return null;

  return (
    <div className="flex shrink-0 flex-col items-end gap-1">
      <div className="flex items-center gap-1.5">
        {subscribed ? (
          <>
            <Button
              color="tertiary"
              size="sm"
              isDisabled={busy}
              onPress={() => void test()}
              iconLeading={sent ? Check : undefined}
            >
              {sent ? "Đã gửi thử" : "Gửi thử"}
            </Button>
            <Button
              color="tertiary"
              size="sm"
              isDisabled={busy}
              onPress={() => void disable()}
              iconLeading={BellOff01}
              aria-label="Tắt thông báo đẩy"
            >
              Tắt
            </Button>
          </>
        ) : (
          <Button
            color="secondary"
            size="sm"
            isDisabled={busy}
            onPress={() => void enable()}
            iconLeading={BellRinging01}
          >
            Bật thông báo đẩy
          </Button>
        )}
      </div>
      {error ? (
        <span
          role="alert"
          className="max-w-56 text-right text-xs text-error-primary"
        >
          {error}
        </span>
      ) : null}
    </div>
  );
};
