import { InputBase } from "@/components/base/input/input";
import { Label } from "@/components/base/input/label";
import { Select } from "@/components/base/select/select";
import type { SelectItemType } from "@/components/base/select/select-shared";

import type { SettingsStatusState } from "./SettingsFieldStatus";
import type {
  ProviderFieldDescriptor,
  ProviderFormState,
  ProviderSettingsBundle,
} from "./providerDescriptors";
import { SecretField } from "./SecretField";
import type { CredentialFieldNotify } from "./credentialClipboard";

/**
 * One renderer for every descriptor field kind, shared by the provider chain
 * cards and the standalone Jev card.
 *
 * The text control is `InputBase` rather than the composed `Input`: this field
 * owns its own label and has no hint slot, and the console styles the control
 * itself (`settings-input`) as one element.
 */
export const ProviderField = ({
  field,
  bundle,
  statusState,
  form,
  onValueChange,
  notify,
}: {
  field: ProviderFieldDescriptor;
  bundle: ProviderSettingsBundle;
  statusState: SettingsStatusState;
  form: ProviderFormState;
  onValueChange: (key: keyof ProviderFormState, value: string) => void;
  notify: CredentialFieldNotify;
}) => {
  if (field.kind === "readonly") {
    return (
      <div className="settings-field">
        <div className="settings-field-label-row">
          <span className="settings-llm-field-label">{field.label}</span>
          {field.note ? (
            <span className="settings-llm-field-note">{field.note}</span>
          ) : null}
        </div>
        <p className="settings-llm-readonly-value">{field.value(bundle)}</p>
      </div>
    );
  }
  if (field.kind === "select") {
    const items: SelectItemType[] = field.options.map((model) => ({
      id: model,
      label: model,
    }));
    const selected = form[field.formKey];

    return (
      <div className="settings-field">
        <Label htmlFor={field.formKey}>{field.label}</Label>
        {/* An empty placeholder keeps a model-less provider blank, exactly as
            the select it replaces rendered an unset value. */}
        <Select
          id={field.formKey}
          size="sm"
          className="uu-scope"
          aria-label={field.label}
          placeholder=""
          items={items}
          selectedKey={selected === "" ? null : selected}
          onSelectionChange={(key) => {
            if (key !== null) onValueChange(field.formKey, String(key));
          }}
          validationBehavior="aria"
        >
          {(item: SelectItemType) => (
            <Select.Item id={item.id} label={item.label} />
          )}
        </Select>
      </div>
    );
  }
  if (field.kind === "text") {
    return (
      <div className="settings-field">
        <Label htmlFor={field.formKey}>{field.label}</Label>
        <InputBase
          id={field.formKey}
          size="sm"
          autoComplete="off"
          value={form[field.formKey]}
          placeholder={field.placeholder(bundle)}
          wrapperClassName="settings-input uu-scope"
          onChange={(event) => onValueChange(field.formKey, event.target.value)}
        />
      </div>
    );
  }

  const status = field.status(bundle);
  return (
    <SecretField
      id={field.formKey}
      label={field.label}
      placeholder={field.placeholder}
      statusState={statusState}
      configured={status.configured}
      preview={status.preview ?? null}
      value={form[field.formKey]}
      onChange={(value) => onValueChange(field.formKey, value)}
      notify={notify}
    />
  );
};
