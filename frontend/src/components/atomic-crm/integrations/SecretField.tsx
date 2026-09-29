import { useState, type ReactNode } from "react";
import { Copy, Eye, EyeOff } from "lucide-react";

import { ButtonUtility } from "@/components/base/buttons/button-utility";
import { InputBase } from "@/components/base/input/input";
import { Label } from "@/components/base/input/label";

import {
  SettingsFieldStatus,
  type SettingsStatusState,
} from "./SettingsFieldStatus";
import {
  copyCredentialFieldValue,
  type CredentialFieldNotify,
} from "./credentialClipboard";

/**
 * One credential-field implementation for every integration page.
 *
 * `SecretField` owns the masking policy: a masked input, an eye that unmasks
 * what is typed locally or fetches the stored plaintext on demand, and — when
 * the page supplies a toast channel — a copy action. `PlainField` owns the
 * non-secret half of the same shell, including its optional copy action.
 *
 * The control, the label and the two icon actions are Untitled UI PRO
 * primitives (`InputBase` / `Label` / `ButtonUtility`). `InputBase` rather than
 * the composed `Input` is deliberate: the field shell already owns the label,
 * the hint and the status marker, and the surrounding console CSS places the
 * input, the reveal and the copy action as sibling grid tracks — the composed
 * wrapper would add a level that breaks both.
 */

type FieldShellProps = {
  id: string;
  label: string;
  configured: boolean;
  statusState: SettingsStatusState;
  /**
   * True (default) always shows the saved/missing badge; false hides it while a
   * field is unconfigured and the status is still loading — an optional field
   * should not advertise a missing value it does not require.
   */
  showMissingStatus?: boolean;
  hint?: string;
  className?: string;
  children: ReactNode;
};

const FieldShell = ({
  id,
  label,
  configured,
  statusState,
  showMissingStatus = true,
  hint,
  className = "",
  children,
}: FieldShellProps) => (
  <div className={`settings-field ${className}`.trim()}>
    <div className="settings-field-label-row">
      <Label htmlFor={id}>{label}</Label>
      {showMissingStatus || configured || statusState !== "ready" ? (
        <SettingsFieldStatus configured={configured} state={statusState} />
      ) : null}
    </div>
    {children}
    {hint ? <span className="settings-field-hint">{hint}</span> : null}
  </div>
);

const CopyButton = ({
  label,
  value,
  notify,
  className,
}: {
  label: string;
  value: string;
  notify: CredentialFieldNotify;
  className: string;
}) => (
  <ButtonUtility
    tooltip={`Sao chép ${label}`}
    size="xs"
    color="tertiary"
    className={className}
    isDisabled={!value}
    onClick={() => void copyCredentialFieldValue(label, value, notify)}
    icon={<Copy />}
  />
);

export type SecretFieldProps = {
  id: string;
  label: string;
  configured: boolean;
  statusState?: SettingsStatusState;
  /** Masked tail of the stored value; shown in place of the placeholder. */
  preview?: string | null;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  hint?: string;
  /** Toast channel; when given, the field also offers a copy action. */
  notify?: CredentialFieldNotify;
  /**
   * Fetches the stored plaintext on demand. Without it the eye only unmasks
   * what is already typed, and the stored secret never leaves the server.
   */
  reveal?: () => Promise<string | null>;
};

export const SecretField = ({
  id,
  label,
  configured,
  statusState = "ready",
  preview = null,
  value,
  onChange,
  placeholder,
  hint,
  notify,
  reveal,
}: SecretFieldProps) => {
  const [isVisible, setIsVisible] = useState(false);
  // Stored secrets are not part of the form state: they are fetched on demand
  // so an unopened field never holds plaintext, and shown read-only so
  // revealing cannot accidentally rewrite the saved value.
  const [revealed, setRevealed] = useState<string | null>(null);
  const [isRevealing, setIsRevealing] = useState(false);
  const isShowing = isVisible || revealed !== null;
  // A field with a stored secret can always fetch it; a field without one can
  // only unmask a value that was just typed.
  const hasRevealAction = reveal ? value !== "" || configured : true;

  const toggleReveal = async () => {
    if (value || !reveal) {
      setIsVisible((visible) => !visible);
      return;
    }
    if (revealed !== null) {
      setRevealed(null);
      return;
    }
    setIsRevealing(true);
    try {
      setRevealed((await reveal()) ?? null);
    } finally {
      setIsRevealing(false);
    }
  };

  return (
    <FieldShell
      id={id}
      label={label}
      configured={configured}
      statusState={statusState}
      hint={hint}
    >
      <div className="settings-sensitive-input">
        {/*
          `uu-scope` re-binds the four utility names this console and Untitled UI
          both define (`bg-primary`, `bg-secondary`, `text-primary`,
          `border-primary`), so the input paints its own white surface instead of
          the brand coral. `[&>button]:hidden` suppresses the primitive's own
          password eye: the reveal action here is the console's, because it can
          fetch the stored plaintext from the server — a local toggle cannot.
        */}
        <InputBase
          id={id}
          size="sm"
          type={isShowing ? "text" : "password"}
          autoComplete="off"
          spellCheck={false}
          readOnly={revealed !== null}
          value={revealed ?? value}
          placeholder={preview ? `Hiện tại: ${preview}` : placeholder}
          wrapperClassName="settings-input uu-scope [&>button]:hidden"
          onChange={(event) => onChange(event.target.value)}
        />
        {hasRevealAction ? (
          <ButtonUtility
            tooltip={isShowing ? `Ẩn ${label}` : `Hiện ${label}`}
            size="xs"
            color="tertiary"
            className="settings-input-action"
            isDisabled={isRevealing}
            onClick={() => void toggleReveal()}
            icon={isShowing ? <EyeOff /> : <Eye />}
          />
        ) : null}
        {notify ? (
          <CopyButton
            label={label}
            value={value}
            notify={notify}
            className="settings-input-action"
          />
        ) : null}
      </div>
    </FieldShell>
  );
};

export type PlainFieldProps = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  configured: boolean;
  statusState?: SettingsStatusState;
  showMissingStatus?: boolean;
  hint?: string;
  /** Toast channel; when given, the field also offers a copy action. */
  notify?: CredentialFieldNotify;
};

export const PlainField = ({
  id,
  label,
  value,
  onChange,
  configured,
  statusState = "ready",
  showMissingStatus = true,
  hint,
  notify,
}: PlainFieldProps) => (
  <FieldShell
    id={id}
    label={label}
    configured={configured}
    statusState={statusState}
    showMissingStatus={showMissingStatus}
    hint={hint}
    // A copy action sits next to the bare input, so the field — not the
    // sensitive-input wrapper — owns the action's layout class.
    className={notify ? "settings-field-has-action" : ""}
  >
    <InputBase
      id={id}
      size="sm"
      type="text"
      autoComplete="off"
      spellCheck={false}
      value={value}
      wrapperClassName="settings-input uu-scope"
      onChange={(event) => onChange(event.target.value)}
    />
    {notify ? (
      <CopyButton
        label={label}
        value={value}
        notify={notify}
        className="settings-copy-app-id settings-input-action"
      />
    ) : null}
  </FieldShell>
);
