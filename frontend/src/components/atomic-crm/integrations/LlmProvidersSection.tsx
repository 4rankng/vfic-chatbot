import { Fragment } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useNotify, useTranslate } from "ra-core";

import { Button } from "@/components/ui/button";

import type { LlmProvider } from "./api";
import type { SettingsStatusState } from "./SettingsFieldStatus";
import type { ProviderPanels } from "./useProviderPanels";
import {
  CHAIN_PANEL_ID_BY_PROVIDER,
  PROVIDER_GROUP_IDS,
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

const PROVIDER_LABELS: Record<LlmProvider, string> = {
  minimax: "MiniMax",
  openrouter: "OpenRouter",
  custom: "Xiaomi",
};

/**
 * The AI Providers view: the failover chain as a ranking board — one card per
 * provider, ordered by the operator's ranking, each with its own probe.
 */
export const LlmProvidersSection = ({
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
  const {
    chain,
    chainEnabled,
    moveProvider,
    providerLastTests,
    providerSaving,
    providerTesting,
  } = panels;
  // Only enabled providers can serve a turn, so the visible rank counts them
  // alone — a disabled card holds its slot but carries no number.
  const servingChain = chain.filter((provider) => chainEnabled[provider]);
  const rankOf = (provider: LlmProvider): number | null => {
    const index = servingChain.indexOf(provider);
    return index === -1 ? null : index + 1;
  };
  const chipOf = (provider: LlmProvider): { label: string; cls: string } => {
    if (!chainEnabled[provider]) return { label: "Tắt", cls: "is-muted" };
    const test = providerLastTests[CHAIN_PANEL_ID_BY_PROVIDER[provider]];
    if (test?.ok) return { label: "Sẵn sàng", cls: "is-success" };
    if (test && !test.ok) return { label: "Lỗi kiểm tra", cls: "is-danger" };
    return { label: "Chưa kiểm tra", cls: "is-muted" };
  };
  const testLineOf = (
    provider: LlmProvider,
  ): { text: string; title?: string; ok: boolean } => {
    const test = providerLastTests[CHAIN_PANEL_ID_BY_PROVIDER[provider]];
    if (!test) return { text: "Chưa kiểm tra", ok: true };
    if (test.ok) {
      return {
        text: `Kiểm tra ${formatRelativeEpoch(test.tested_at)} · ${test.latency_ms ?? "?"}ms`,
        ok: true,
      };
    }
    const raw = test.error || "";
    return { text: describeProviderTestError(raw), title: raw, ok: false };
  };
  // Card header: the failover rank replaces a decorative glyph, so the card
  // states its own position in the chain.
  const rankBadgeOf = (provider: LlmProvider) => {
    const rank = rankOf(provider);
    return (
      <span
        className={`settings-llm-rank${rank === 1 ? " is-default" : ""}${
          rank === null ? " is-off" : ""
        }`}
        aria-hidden="true"
      >
        {rank ?? "—"}
      </span>
    );
  };
  const cardMetaOf = (provider: LlmProvider) => {
    const index = chain.indexOf(provider);
    const movable = provider !== panels.llmDefaultProvider;
    const chip = chipOf(provider);
    return (
      <>
        {movable ? (
          <span className="settings-llm-moves">
            <button
              type="button"
              className="settings-llm-move"
              disabled={index <= 1}
              onClick={() => moveProvider(provider, -1)}
              aria-label={`Tăng ưu tiên cho ${PROVIDER_LABELS[provider]}`}
            >
              <ChevronUp className="size-4" />
            </button>
            <button
              type="button"
              className="settings-llm-move"
              disabled={index === chain.length - 1}
              onClick={() => moveProvider(provider, 1)}
              aria-label={`Giảm ưu tiên cho ${PROVIDER_LABELS[provider]}`}
            >
              <ChevronDown className="size-4" />
            </button>
          </span>
        ) : null}
        <span className={`settings-llm-chip ${chip.cls}`}>{chip.label}</span>
      </>
    );
  };
  const roleRowOf = (provider: LlmProvider, switchId: string) => (
    <div className="settings-llm-role-row">
      <label className="settings-llm-radio">
        <input
          type="radio"
          name="llm_default_provider"
          checked={panels.llmDefaultProvider === provider}
          disabled={!chainEnabled[provider]}
          onChange={() => panels.setLlmDefaultProvider(provider)}
        />
        <span>Chạy đầu tiên</span>
      </label>
      <ProviderSwitchField
        id={switchId}
        label="Kích hoạt"
        checked={chainEnabled[provider]}
        onCheckedChange={(checked) =>
          panels.handleProviderEnabledChange(provider, checked)
        }
      />
    </div>
  );
  const verifyRowOf = (provider: LlmProvider, ready: boolean) => {
    const line = testLineOf(provider);
    const panelId = CHAIN_PANEL_ID_BY_PROVIDER[provider];
    const anyChainTesting = PROVIDER_GROUP_IDS.chain.some(
      (id) => providerTesting[id],
    );
    return (
      <div className="settings-llm-verify">
        <span
          className={`settings-llm-testline${line.ok ? "" : " is-error"}`}
          title={line.title}
        >
          {line.text}
        </span>
        <Button
          type="button"
          variant="outline"
          className="tt-btn-touch"
          onClick={() => {
            void panels.testProviderPanel(panelId);
          }}
          disabled={anyChainTesting || !ready}
          aria-busy={providerTesting[panelId]}
        >
          {providerTesting[panelId]
            ? translate("crm.common.testing")
            : translate("crm.common.test")}
        </Button>
      </div>
    );
  };
  const disabledProviders = chain.filter((provider) => !chainEnabled[provider]);

  return (
    <SettingsSectionPanel id="settings-llm-providers">
      <p className="settings-llm-chain" data-slot="settings-llm-chain">
        <span className="settings-llm-chain-label">Thứ tự dự phòng</span>
        {servingChain.length === 0 ? (
          <span className="settings-llm-chain-empty">
            Chưa bật nhà cung cấp nào — bot không thể trả lời.
          </span>
        ) : (
          servingChain.map((provider, index) => (
            <Fragment key={provider}>
              {index > 0 ? (
                <span className="settings-llm-chain-arrow" aria-hidden>
                  →
                </span>
              ) : null}
              <span
                className={`settings-llm-chain-item is-on${
                  index === 0 ? " is-default" : ""
                }`}
              >
                <em>{index + 1}</em>
                {PROVIDER_LABELS[provider]}
              </span>
            </Fragment>
          ))
        )}
        {disabledProviders.length > 0 ? (
          <span className="settings-llm-chain-off">
            Đang tắt:{" "}
            {disabledProviders
              .map((provider) => PROVIDER_LABELS[provider])
              .join(", ")}
          </span>
        ) : null}
      </p>

      <div className="settings-grid settings-grid-models">
        {/* Cards render in failover order, so the board itself is the
            ranking: position, rank badge, and reorder control agree. */}
        {chain.map((provider) => {
          const descriptor =
            PROVIDER_PANELS_BY_ID[CHAIN_PANEL_ID_BY_PROVIDER[provider]];
          const ready = descriptor.readEnabled(bundle) !== null;
          return (
            <SettingsGroup
              key={provider}
              className={`settings-llm-card${
                chainEnabled[provider] ? "" : " is-off"
              }`}
              title={PROVIDER_LABELS[provider]}
              icon={rankBadgeOf(provider)}
              meta={cardMetaOf(provider)}
            >
              {roleRowOf(provider, descriptor.enableKey)}
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
              {verifyRowOf(provider, ready)}
            </SettingsGroup>
          );
        })}
      </div>

      <div
        className={`settings-llm-footer${panels.dirty.chain ? " is-dirty" : ""}`}
      >
        <Button
          type="button"
          variant="ghost"
          className="tt-btn-touch"
          onClick={() => panels.discardProviderPanels("chain")}
          disabled={!panels.dirty.chain || providerSaving.chain}
        >
          Huỷ
        </Button>
        <Button
          type="button"
          className="settings-primary-action tt-btn-touch"
          onClick={() => {
            void panels.saveProviderPanels("chain");
          }}
          disabled={!panels.dirty.chain || providerSaving.chain}
        >
          {providerSaving.chain
            ? translate("crm.common.saving")
            : translate("crm.common.save_changes")}
        </Button>
        <span className="settings-llm-footer-note">
          {panels.dirty.chain
            ? translate("crm.common.unsaved_changes")
            : translate("crm.common.token_encrypted_hint")}
        </span>
      </div>
    </SettingsSectionPanel>
  );
};
