import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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
    return (
      <div className="settings-field">
        <Label htmlFor={field.formKey}>{field.label}</Label>
        <Select
          value={form[field.formKey]}
          onValueChange={(value) => onValueChange(field.formKey, value)}
        >
          <SelectTrigger id={field.formKey} className="settings-input">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {field.options.map((model) => (
              <SelectItem key={model} value={model}>
                {model}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }
  if (field.kind === "text") {
    return (
      <div className="settings-field">
        <Label htmlFor={field.formKey}>{field.label}</Label>
        <Input
          id={field.formKey}
          className="settings-input"
          autoComplete="off"
          value={form[field.formKey]}
          placeholder={field.placeholder(bundle)}
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
