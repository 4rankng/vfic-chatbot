import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNotify } from "ra-core";

import { zaloIntegrationGateway, type ZaloSettings } from "./api";
import {
  buildZaloUpdatePayload,
  type ZaloFormState,
  type ZaloSettingsScope,
} from "./zaloUpdatePayload";
import { integrationSettingsKeys } from "./useSettingsBundle";

/** One Zalo channel scope; "all" belongs to the payload builder, not the UI. */
export type ZaloChannelScope = Exclude<ZaloSettingsScope, "all">;

const ZALO_CHANNEL_LABELS: Record<ZaloChannelScope, string> = {
  bot: "Zalo Chatbot",
  oa: "Zalo OA",
};

const ZALO_TEST_FIELD_LABELS: Record<string, string> = {
  zalo_bot_token: "Bot Token",
  zalo_oa_app_id: "Zalo App ID",
  zalo_oa_secret_key: "Bot Secret",
  zalo_oa_access_token: "OA Access Token",
  zalo_oa_refresh_token: "OA Refresh Token",
};

const emptyZaloForm: ZaloFormState = {
  zalo_bot_token: "",
  zalo_bot_webhook_secret: "",
  zalo_oa_app_id: "",
  zalo_oa_secret_key: "",
  zalo_oa_access_token: "",
  zalo_oa_refresh_token: "",
};

/**
 * Owns the Zalo channel form: the draft state, the changed-payload save and the
 * "save then probe" channel tests. The save is a TanStack Query mutation that
 * writes the PUT response straight into the settings cache, so the panel never
 * needs a manual reload.
 */
export const useZaloForm = ({
  settings,
}: {
  settings: ZaloSettings | null;
}) => {
  const notify = useNotify();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ZaloFormState>(emptyZaloForm);
  const [channelTesting, setChannelTesting] = useState<
    Record<ZaloChannelScope, boolean>
  >({ bot: false, oa: false });
  const seeded = useRef(false);
  const testingRef = useRef(false);

  // Seed the plain App ID once, when settings first arrive: the id is the only
  // field the server echoes back, and an in-progress edit must survive a
  // background refetch.
  useEffect(() => {
    if (seeded.current || !settings) return;
    seeded.current = true;
    setForm((current) => ({
      ...current,
      zalo_oa_app_id: settings.zalo_oa_app_id.value ?? "",
    }));
  }, [settings]);

  const saveMutation = useMutation({
    mutationFn: (body: Partial<ZaloFormState>) =>
      zaloIntegrationGateway.saveZaloSettings(body),
    onSuccess: (saved, submitted) => {
      queryClient.setQueryData(integrationSettingsKeys.zalo, saved);
      // Clear only the values this scope saved. The other channel's draft,
      // and any newer edit typed while this request ran, remain unsaved.
      setForm((current) => {
        const next = { ...current };
        for (const key of Object.keys(submitted) as (keyof ZaloFormState)[]) {
          if (current[key].trim() === submitted[key]) {
            next[key] =
              key === "zalo_oa_app_id"
                ? (saved.zalo_oa_app_id.value ?? "")
                : "";
          }
        }
        return next;
      });
    },
  });

  const channelTestMutation = useMutation({
    mutationFn: (scope: ZaloChannelScope) =>
      scope === "bot"
        ? zaloIntegrationGateway.testBotConnection()
        : zaloIntegrationGateway.testOaConnection(),
  });

  // Save before probing: the test must run against what the server holds, and a
  // scope-limited payload never rewrites the other channel's stale values.
  const saveChanges = async (scope: ZaloChannelScope) => {
    const payload = buildZaloUpdatePayload(
      form,
      settings?.zalo_oa_app_id.value,
      scope,
    );
    if (Object.keys(payload).length === 0) return null;
    return saveMutation.mutateAsync(payload);
  };

  const testChannel = async (scope: ZaloChannelScope) => {
    if (testingRef.current || !settings) return;
    testingRef.current = true;
    const label = ZALO_CHANNEL_LABELS[scope];
    setChannelTesting((current) => ({ ...current, [scope]: true }));
    try {
      await saveChanges(scope);
      const result = await channelTestMutation.mutateAsync(scope);
      if (result.connected) {
        // Show OA-specific warnings even when connected (e.g. secret key
        // invalid but access token still works — will break on next refresh).
        const warnings: string[] = [];
        if (result.oa_secret_valid === false) {
          warnings.push(
            "⚠️ Secret Key không hợp lệ — sẽ lỗi khi làm mới token",
          );
        }
        if (warnings.length > 0) {
          notify(`Kết nối ${label} thành công, nhưng: ${warnings.join("; ")}`, {
            type: "warning",
          });
        } else {
          notify(`Kết nối ${label} thành công`, { type: "success" });
        }
        return;
      }
      if (result.missing.length > 0) {
        const missing = result.missing
          .map((key) => ZALO_TEST_FIELD_LABELS[key] ?? key)
          .join(", ");
        notify(`Thiếu cấu hình: ${missing}`, { type: "warning" });
        return;
      }
      // Show the most specific error from the new diagnostics
      if (result.oa_secret_valid === false) {
        notify(
          "❌ Secret Key không hợp lệ! Lấy từ Zalo OA dashboard → Cài đặt → API",
          { type: "error" },
        );
        return;
      }
      if (result.oa_refresh_ok === false && result.oa_token_expired) {
        notify(
          "❌ Token hết hạn và không thể làm mới. Kiểm tra Secret Key và Refresh Token",
          { type: "error" },
        );
        return;
      }
      notify(result.errors.join("; ") || `Không kết nối được ${label}`, {
        type: "warning",
      });
    } catch {
      notify(
        `Không lưu hoặc kiểm tra được kết nối ${label}. Vui lòng thử lại.`,
        { type: "error" },
      );
    } finally {
      testingRef.current = false;
      setChannelTesting((current) => ({ ...current, [scope]: false }));
    }
  };

  return {
    form,
    setValue: (key: keyof ZaloFormState, value: string) => {
      setForm((current) => ({ ...current, [key]: value }));
    },
    channelTesting,
    testChannel,
  };
};
