import { useNotify, useTranslate } from "ra-core";

import { Button } from "@/components/base/buttons/button";

import type { SettingsStatusState } from "./SettingsFieldStatus";
import { SettingsGroupStatus } from "./SettingsFieldStatus";
import type { ProviderPanels } from "./useProviderPanels";
import {
  PROVIDER_PANELS_BY_ID,
  type ProviderSettingsBundle,
} from "./providerDescriptors";
import { ProviderField } from "./ProviderField";
import {
  ProviderSwitchField,
  SettingsGroup,
  SettingsSectionPanel,
} from "./SettingsGroup";
import { describeProviderTestError, formatRelativeEpoch } from "./statusCopy";

/**
 * The Jev view: one standalone provider card outside the failover chain, with
 * the same descriptor-driven fields, probe and save footer as the chain cards.
 */
export const JevSection = ({
  panels,
  bundle,
  statusState,
}: {
  panels: ProviderPanels;
  bundle: ProviderSettingsBundle;
  statusState: SettingsStatusState;
}) => {
  const notify = useNotify();
  const translate = useTranslate();
  const descriptor = PROVIDER_PANELS_BY_ID.jev;
  const JevIcon = descriptor.icon;
  const ready = descriptor.readEnabled(bundle) !== null;
  const lastTest = panels.providerLastTests.jev;
  const testLine: { text: string; title?: string; ok: boolean } = lastTest
    ? lastTest.ok
      ? {
          text: `Kiểm tra ${formatRelativeEpoch(lastTest.tested_at)} · ${lastTest.latency_ms ?? "?"}ms`,
          ok: true,
        }
      : {
          text: describeProviderTestError(lastTest.error || ""),
          title: lastTest.error ?? undefined,
          ok: false,
        }
    : { text: "Chưa kiểm tra", ok: true };
  const jevStatus = descriptor.status?.(bundle, panels.providerEnabled.jev);

  return (
    <SettingsSectionPanel id="settings-jev">
      <fieldset
        className="contents"
        disabled={
          panels.providerSaving.standalone ||
          panels.providerTesting.jev ||
          !ready
        }
        aria-busy={
          panels.providerSaving.standalone || panels.providerTesting.jev
        }
      >
        <legend className="sr-only">Thông tin kết nối Jev</legend>
        <div className="settings-grid settings-grid-models">
          <SettingsGroup
            className="settings-llm-card"
            title={descriptor.title}
            description={descriptor.description}
            icon={JevIcon ? <JevIcon className="size-4" /> : null}
            meta={
              jevStatus ? (
                <SettingsGroupStatus
                  configured={jevStatus.configured}
                  total={jevStatus.total}
                  disabled={jevStatus.disabled}
                  state={statusState}
                />
              ) : null
            }
          >
            <ProviderSwitchField
              id={descriptor.enableKey}
              label="Kích hoạt"
              checked={panels.providerEnabled.jev}
              onCheckedChange={(checked) =>
                panels.setPanelEnabled("jev", checked)
              }
            />
            {descriptor.fields.map((field) => (
              <ProviderField
                key={field.kind === "readonly" ? field.label : field.formKey}
                field={field}
                bundle={bundle}
                statusState={statusState}
                form={panels.providerForm}
                onValueChange={panels.setProviderFormValue}
                notify={notify}
              />
            ))}
            <div className="settings-llm-verify">
              <span
                className={`settings-llm-testline${testLine.ok ? "" : " is-error"}`}
                title={testLine.title}
              >
                {testLine.text}
              </span>
              <Button
                type="button"
                color="secondary"
                className="uu-scope tt-btn-touch"
                onClick={() => {
                  void panels.testProviderPanel("jev");
                }}
                isDisabled={panels.providerTesting.jev || !ready}
                aria-busy={panels.providerTesting.jev}
              >
                {panels.providerTesting.jev
                  ? translate("crm.common.testing")
                  : translate("crm.common.test")}
              </Button>
            </div>
          </SettingsGroup>
        </div>

        <div
          className={`settings-llm-footer${
            panels.dirty.standalone ? " is-dirty" : ""
          }`}
        >
          <Button
            type="button"
            color="primary"
            className="settings-primary-action tt-btn-touch"
            onClick={() => {
              void panels.saveProviderPanels("standalone");
            }}
            isDisabled={
              !panels.dirty.standalone || panels.providerSaving.standalone
            }
          >
            {panels.providerSaving.standalone
              ? translate("crm.common.saving")
              : translate("crm.common.save_changes")}
          </Button>
          <span className="settings-llm-footer-note">
            {panels.dirty.standalone
              ? translate("crm.common.unsaved_changes")
              : translate("crm.common.token_encrypted_hint")}
          </span>
        </div>
      </fieldset>
    </SettingsSectionPanel>
  );
};
