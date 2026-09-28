import { useState } from "react";
import { usePermissions, useTranslate } from "ra-core";

import { useProviderPanels } from "./useProviderPanels";
import { useSettingsBundle } from "./useSettingsBundle";
import { useZaloForm } from "./useZaloForm";
import {
  AgentsSettingsSection,
  MessengerSettingsSection,
  UsersSettingsSection,
} from "./EmbeddedSettingsSections";
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
 * The Settings resource: a console shell that switches between seven section
 * views. Each view owns its own state and actions; this page only decides which
 * one is on screen and where the OAuth callback should land.
 */
export const SettingsConsolePage = () => {
  const translate = useTranslate();
  const { permissions, isPending: permissionsPending } = usePermissions();
  const [activeItemId, setActiveItemId] = useState<SettingsItemId>(
    resolveInitialSettingsItemId,
  );

  const isAdmin = !permissionsPending && permissions === "admin";
  const settings = useSettingsBundle(isAdmin);
  const zaloForm = useZaloForm({ settings: settings.zalo });
  const panels = useProviderPanels(settings.providers);

  if (!permissionsPending && permissions !== "admin") {
    return (
      <SettingsWorkspace>
        <div className="settings-workspace-content text-foreground">
          <div className="ops-page-shell settings-page-shell">
            <div className="ops-panel settings-access-denied">
              {translate("ra.auth.access_denied", { _: "Access denied" })}
            </div>
          </div>
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
      case "settings-agents":
        return <AgentsSettingsSection />;
      case "settings-users":
        return <UsersSettingsSection />;
      case "settings-facebook-messenger":
        return <MessengerSettingsSection />;
    }
  };

  return (
    <SettingsChrome activeItemId={activeItemId} onItemSelect={setActiveItemId}>
      {renderSection()}
    </SettingsChrome>
  );
};
