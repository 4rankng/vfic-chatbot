import { useState } from "react";
import { usePermissions } from "ra-core";
import { ShieldOff } from "lucide-react";
import { Button } from "@/components/base/buttons/button";
import { EmptyState, PageShell } from "../kit/page-shell";
import { PageHeading } from "../kit/page-heading";
import { LoadingState } from "../misc/LoadingState";

import { useProviderPanels } from "./useProviderPanels";
import { useSettingsBundle } from "./useSettingsBundle";
import { useZaloForm } from "./useZaloForm";
import {
  MessengerSettingsSection,
  UsersSettingsSection,
} from "./EmbeddedSettingsSections";
import { GeocoderSection } from "./GeocoderSection";
import { JevSection } from "./JevSection";
import { LlmProvidersSection } from "./LlmProvidersSection";
import { TingtingSection } from "./TingtingSection";
import { SettingsChrome, SettingsWorkspace } from "./SettingsChrome";
import { ZaloChannelSection } from "./ZaloChannelSection";
import {
  resolveInitialSettingsItemId,
  type SettingsItemId,
} from "./settingsNav";

/**
 * The Settings resource: a console shell that switches between six section
 * views. Each view owns its own state and actions; this page only decides which
 * one is on screen and where the OAuth callback should land.
 */
export const SettingsConsolePage = () => {
  const { permissions, isPending: permissionsPending } = usePermissions();
  const [activeItemId, setActiveItemId] = useState<SettingsItemId>(
    resolveInitialSettingsItemId,
  );

  const isAdmin = !permissionsPending && permissions === "admin";
  const settings = useSettingsBundle(isAdmin);
  const zaloForm = useZaloForm({ settings: settings.zalo });
  const panels = useProviderPanels(settings.providers);

  if (permissionsPending) {
    return (
      <SettingsWorkspace>
        <LoadingState label="Đang kiểm tra quyền truy cập…" />
      </SettingsWorkspace>
    );
  }

  if (!permissionsPending && permissions !== "admin") {
    return (
      <SettingsWorkspace>
        <div className="settings-workspace-content text-foreground">
          <PageShell>
            <PageHeading title="Cài đặt" />
            <EmptyState
              icon={<ShieldOff className="size-6" aria-hidden="true" />}
              title="Bạn chưa có quyền truy cập"
              description="Liên hệ quản trị viên để thay đổi cấu hình hệ thống."
            />
          </PageShell>
        </div>
      </SettingsWorkspace>
    );
  }

  const renderSection = () => {
    switch (activeItemId) {
      case "settings-zalo-channel":
        return (
          <ZaloChannelSection
            settings={settings.zalo}
            statusState={settings.statusState}
            form={zaloForm.form}
            onValueChange={zaloForm.setValue}
            channelTesting={zaloForm.channelTesting}
            onTestChannel={zaloForm.testChannel}
          />
        );
      case "settings-llm-providers":
        return (
          <LlmProvidersSection
            panels={panels}
            bundle={settings.providers}
            statusState={settings.statusState}
          />
        );
      case "settings-jev":
        return (
          <JevSection
            panels={panels}
            bundle={settings.providers}
            statusState={settings.statusState}
          />
        );
      case "settings-tingting":
        return <TingtingSection />;
      case "settings-geocoder":
        return <GeocoderSection />;
      case "settings-users":
        return <UsersSettingsSection />;
      case "settings-facebook-messenger":
        return <MessengerSettingsSection />;
    }
  };

  return (
    <SettingsChrome activeItemId={activeItemId} onItemSelect={setActiveItemId}>
      {settings.statusState === "error" &&
      [
        "settings-zalo-channel",
        "settings-llm-providers",
        "settings-jev",
      ].includes(activeItemId) ? (
        <div className="settings-load-error" role="alert">
          <span>Chưa tải được cấu hình tích hợp.</span>
          <Button
            type="button"
            color="secondary"
            size="sm"
            className="uu-scope"
            isDisabled={settings.isFetching}
            isLoading={settings.isFetching}
            showTextWhileLoading
            onClick={settings.retry}
          >
            Thử lại
          </Button>
        </div>
      ) : null}
      {renderSection()}
    </SettingsChrome>
  );
};
