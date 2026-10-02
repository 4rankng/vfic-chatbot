import { MessageCircle, PlugZap, Wifi } from "lucide-react";
import { useNotify, useTranslate } from "ra-core";

import { AlertFloating } from "@/components/application/alerts/alerts";
import { Button } from "@/components/base/buttons/button";

import type { ZaloOaSignatureHealth, ZaloSettings } from "./api";
import type { SettingsStatusState } from "./SettingsFieldStatus";
import { SettingsGroupStatus } from "./SettingsFieldStatus";
import type { ZaloChannelScope } from "./useZaloForm";
import type { ZaloFormState } from "./zaloUpdatePayload";
import { PlainField, SecretField } from "./SecretField";
import { SettingsGroup, SettingsSectionPanel } from "./SettingsGroup";
import { formatRelativeEpoch } from "./statusCopy";

const describeOaSignatureHealth = (health: ZaloOaSignatureHealth | null) => {
  if (!health || !health.last_status) {
    return {
      message:
        "Chưa có sự kiện webhook thực nào — trạng thái chữ ký sẽ cập nhật khi Zalo gửi tin nhắn đầu tiên.",
      type: "info" as const,
    };
  }
  if (health.last_status === "verified") {
    return {
      message: `Chữ ký webhook hợp lệ — cập nhật ${formatRelativeEpoch(health.last_ts)}.`,
      type: "success" as const,
    };
  }
  return {
    message: `Chữ ký webhook bị từ chối — Webhook Secret có thể sai${health.consec_failures ? ` (×${health.consec_failures})` : ""}. Cập nhật ${formatRelativeEpoch(health.last_mismatch_ts ?? health.last_ts)}.`,
    type: "warning" as const,
  };
};

/** The Zalo channel view: Bot Platform and OA credentials, plus channel tests. */
export const ZaloChannelSection = ({
  settings,
  statusState,
  form,
  onValueChange,
  channelTesting,
  onTestChannel,
}: {
  settings: ZaloSettings | null;
  statusState: SettingsStatusState;
  form: ZaloFormState;
  onValueChange: (key: keyof ZaloFormState, value: string) => void;
  channelTesting: Record<ZaloChannelScope, boolean>;
  onTestChannel: (scope: ZaloChannelScope) => void;
}) => {
  const notify = useNotify();
  const translate = useTranslate();
  const webhookHealth = describeOaSignatureHealth(
    settings?.zalo_oa_webhook_signature ?? null,
  );
  const botConfigured = [
    settings?.zalo_bot_token.configured,
    settings?.zalo_bot_webhook_secret.configured,
  ].filter(Boolean).length;
  const oaConfigured = [
    settings?.zalo_oa_app_id.configured,
    settings?.zalo_oa_secret_key.configured,
    settings?.zalo_oa_access_token.configured,
    settings?.zalo_oa_refresh_token.configured,
  ].filter(Boolean).length;

  return (
    <SettingsSectionPanel id="settings-zalo-channel">
      <fieldset
        className="contents"
        disabled={channelTesting.bot || channelTesting.oa || !settings}
        aria-busy={channelTesting.bot || channelTesting.oa}
      >
        <legend className="sr-only">Thông tin kết nối Zalo</legend>
        <div className="settings-grid settings-grid-zalo">
          <SettingsGroup
            className="settings-zalo-bot"
            title="Zalo Chatbot"
            description="Thông tin kết nối Bot Platform."
            icon={<PlugZap className="size-4" />}
            meta={
              <SettingsGroupStatus
                configured={botConfigured}
                total={2}
                state={statusState}
              />
            }
            defaultOpen
          >
            <SecretField
              id="zalo_bot_token"
              label="Bot Token"
              placeholder="Nhập giá trị"
              statusState={statusState}
              configured={settings?.zalo_bot_token.configured ?? false}
              preview={settings?.zalo_bot_token.preview ?? null}
              value={form.zalo_bot_token}
              onChange={(value) => onValueChange("zalo_bot_token", value)}
              notify={notify}
            />
            <SecretField
              id="zalo_bot_webhook_secret"
              label="Bot Secret"
              placeholder="Nhập giá trị"
              statusState={statusState}
              configured={settings?.zalo_bot_webhook_secret.configured ?? false}
              preview={settings?.zalo_bot_webhook_secret.preview ?? null}
              value={form.zalo_bot_webhook_secret}
              onChange={(value) =>
                onValueChange("zalo_bot_webhook_secret", value)
              }
              notify={notify}
            />
            <div className="settings-oa-actions">
              <Button
                type="button"
                color="primary"
                iconLeading={<Wifi className="size-4" />}
                className="settings-test-button settings-primary-action tt-btn-touch"
                onClick={() => onTestChannel("bot")}
                isDisabled={channelTesting.bot || !settings}
                aria-busy={channelTesting.bot}
              >
                {channelTesting.bot
                  ? translate("crm.common.testing")
                  : translate("crm.common.save_and_test")}
              </Button>
            </div>
          </SettingsGroup>

          <SettingsGroup
            title="Zalo OA"
            description="Ứng dụng và quyền truy cập Official Account."
            icon={<MessageCircle className="size-4" />}
            meta={
              <SettingsGroupStatus
                configured={oaConfigured}
                total={4}
                state={statusState}
              />
            }
          >
            <div className="settings-oa-fields">
              <PlainField
                id="zalo_oa_app_id"
                label="Zalo App ID"
                configured={settings?.zalo_oa_app_id.configured ?? false}
                statusState={statusState}
                value={form.zalo_oa_app_id}
                onChange={(value) => onValueChange("zalo_oa_app_id", value)}
                notify={notify}
              />

              <SecretField
                id="zalo_oa_secret_key"
                label="App Secret"
                placeholder="Nhập giá trị"
                statusState={statusState}
                configured={settings?.zalo_oa_secret_key.configured ?? false}
                preview={settings?.zalo_oa_secret_key.preview ?? null}
                value={form.zalo_oa_secret_key}
                onChange={(value) => onValueChange("zalo_oa_secret_key", value)}
                notify={notify}
              />
              <SecretField
                id="zalo_oa_access_token"
                label="OA Access Token"
                placeholder="Nhập giá trị"
                statusState={statusState}
                configured={settings?.zalo_oa_access_token.configured ?? false}
                preview={settings?.zalo_oa_access_token.preview ?? null}
                value={form.zalo_oa_access_token}
                onChange={(value) =>
                  onValueChange("zalo_oa_access_token", value)
                }
                notify={notify}
              />
              <SecretField
                id="zalo_oa_refresh_token"
                label="OA Refresh Token"
                placeholder="Nhập giá trị"
                statusState={statusState}
                configured={settings?.zalo_oa_refresh_token.configured ?? false}
                preview={settings?.zalo_oa_refresh_token.preview ?? null}
                value={form.zalo_oa_refresh_token}
                onChange={(value) =>
                  onValueChange("zalo_oa_refresh_token", value)
                }
                notify={notify}
              />
              <div className="settings-oa-actions">
                <Button
                  type="button"
                  color="primary"
                  iconLeading={<Wifi className="size-4" />}
                  className="settings-test-button settings-primary-action tt-btn-touch"
                  onClick={() => onTestChannel("oa")}
                  isDisabled={channelTesting.oa || !settings}
                  aria-busy={channelTesting.oa}
                >
                  {channelTesting.oa
                    ? translate("crm.common.testing")
                    : translate("crm.common.save_and_test")}
                </Button>
              </div>
              <details className="settings-advanced settings-webhook-health">
                <summary className="settings-advanced-summary">Webhook</summary>
                {/*
                The health line is an operator-facing alert, so it uses the
                Untitled UI alert anatomy. `title` carries the sentence and
                `description`/`confirmLabel` stay empty: this alert reports, it
                asks nothing, and the alert renders no action for them.
                `[&_p]:whitespace-normal` un-clips the alert's one-line banner
                `md:truncate`, so a long status sentence wraps instead of
                ending in an ellipsis.
              */}
                <div role="status" className="uu-scope [&_p]:whitespace-normal">
                  <AlertFloating
                    color={
                      webhookHealth.type === "info"
                        ? "default"
                        : webhookHealth.type
                    }
                    title={webhookHealth.message}
                    description=""
                    confirmLabel=""
                  />
                </div>
              </details>
            </div>
          </SettingsGroup>
        </div>
      </fieldset>
    </SettingsSectionPanel>
  );
};
