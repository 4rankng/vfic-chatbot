import type { ReactNode } from "react";
import {
  useInput,
  useTranslate,
  type InputProps as ReactAdminInputProps,
} from "ra-core";
import { Input as UntitledInput } from "@/components/base/input/input";
import { TextArea as UntitledTextArea } from "@/components/base/textarea/textarea";
import { Select as UntitledSelect } from "@/components/base/select/select";
import type { SelectItemType } from "@/components/base/select/select-shared";
import { Checkbox as UntitledCheckbox } from "@/components/base/checkbox/checkbox";
import { Toggle as UntitledToggle } from "@/components/base/toggle/toggle";
import { cx } from "@/utils/cx";

/**
 * React-admin bound form controls on Untitled UI v8 (React Aria) primitives.
 *
 * Every control is a thin adapter, not a second form engine: `useInput` is
 * react-admin's own hook (its `Form` is a react-hook-form `FormProvider`), so a
 * field registered here validates, formats, parses and submits exactly like the
 * `@/components/admin/*-input` controls it replaces. The screens swap the
 * control, not the form.
 *
 * Two rules apply to every control in this file.
 *
 * 1. `validationBehavior="aria"` wherever React Aria exposes it. Its default
 *    `native` behaviour writes the `required` attribute onto the input, so the
 *    browser blocks the form's submit before react-admin's validation runs and
 *    the user gets a browser bubble instead of the console's Vietnamese error.
 *    The controls that render a native form element (text, textarea, select,
 *    checkbox) therefore pin it. React Aria's `Switch` cannot: its props type
 *    omits `validationBehavior`, `isRequired` and `isInvalid` outright and its
 *    input only ever becomes `required` when `isRequired` is passed — which this
 *    control never does. A toggle always has a value, so there is no empty
 *    toggle for a native bubble to fire on.
 * 2. `uu-scope` on the control's own root. Outside it the four utility names
 *    this console and Untitled UI both define (`bg-primary`, `bg-secondary`,
 *    `text-primary`, `border-primary`) keep the console's meaning and the
 *    control paints with the brand coral fill instead of a white input surface.
 *    See `src/styles/untitledui-theme.css`.
 *
 * Design rationale: `frontend/AGENTS.md` § "UI/UX Component Sourcing".
 */

type FieldProps = {
  /** Record field this control reads and writes. */
  source: string;
  label: string;
  hint?: ReactNode;
  /** Renders the console's required marker and `aria-required`. */
  isRequired?: boolean;
  validate?: ReactAdminInputProps["validate"];
  defaultValue?: unknown;
  disabled?: boolean;
  readOnly?: boolean;
  className?: string;
  id?: string;
};

/**
 * react-admin stores a validator's result in a react-hook-form error as
 * `@@react-admin@@<json>` so that the message and its interpolation args stay
 * separate. react-admin's own `ValidationError` does the unwrapping; this is the
 * same unwrap against `useTranslate`, kept local because the console only needs
 * "render the field's message in Vietnamese".
 */
const ERROR_PREFIX = "@@react-admin@@";

const FieldErrorText = ({ error }: { error: string }) => {
  const translate = useTranslate();
  let message: unknown = error;
  let args: Record<string, unknown> = {};

  if (error.startsWith(ERROR_PREFIX)) {
    try {
      const parsed = JSON.parse(error.slice(ERROR_PREFIX.length)) as {
        message?: unknown;
        args?: Record<string, unknown>;
      };
      message = parsed.message ?? error;
      args = parsed.args ?? {};
    } catch {
      message = error;
    }
  }

  if (typeof message !== "string") return <>{error}</>;

  return <>{translate(message, { _: message, ...args })}</>;
};

const errorNode = (error: { message?: string } | undefined): ReactNode =>
  error?.message ? (
    <FieldErrorText error={error.message} />
  ) : error ? (
    "Giá trị chưa hợp lệ."
  ) : undefined;

/**
 * A labelled form row: label, control, then one line of hint or error. Used by
 * the controls whose primitive renders no label of its own (`FormToggle`), so
 * the error keeps the console's error colour instead of the primitive's
 * tertiary hint colour.
 */
const FormFieldRow = ({
  label,
  htmlFor,
  hint,
  error,
  className,
  children,
}: {
  label: string;
  htmlFor?: string;
  hint?: ReactNode;
  error?: ReactNode;
  className?: string;
  children: ReactNode;
}) => (
  <div className={cx("flex min-w-0 flex-col gap-1.5", className)}>
    <label
      htmlFor={htmlFor}
      className="text-label font-medium text-[var(--workspace-ink)]"
    >
      {label}
    </label>
    {children}
    {error ? (
      <p role="alert" className="text-helper text-[var(--workspace-danger)]">
        {error}
      </p>
    ) : hint ? (
      <p className="text-helper text-[var(--workspace-ink-muted)]">{hint}</p>
    ) : null}
  </div>
);

export const FormTextInput = ({
  source,
  label,
  hint,
  isRequired,
  validate,
  defaultValue,
  disabled,
  readOnly,
  className,
  id,
  type = "text",
  placeholder,
  autoComplete,
  autoFocus,
  inputClassName,
}: FieldProps & {
  type?: "text" | "email" | "password";
  placeholder?: string;
  autoComplete?: string;
  autoFocus?: boolean;
  inputClassName?: string;
}) => {
  const {
    id: inputId,
    field,
    fieldState,
    isRequired: required,
  } = useInput({ source, label, validate, defaultValue, isRequired, id });

  return (
    <UntitledInput
      id={inputId}
      className={cx("uu-scope", className)}
      wrapperClassName={inputClassName}
      name={field.name}
      ref={field.ref}
      type={type}
      label={label}
      placeholder={placeholder}
      autoComplete={autoComplete}
      autoFocus={autoFocus}
      value={
        typeof field.value === "string" ? field.value : String(field.value ?? "")
      }
      onChange={(value: string) => field.onChange(value)}
      onBlur={field.onBlur}
      validationBehavior="aria"
      isRequired={required}
      isDisabled={disabled ?? field.disabled}
      isReadOnly={readOnly}
      isInvalid={Boolean(fieldState.error)}
      hint={errorNode(fieldState.error) ?? hint}
    />
  );
};

export const FormTextArea = ({
  source,
  label,
  hint,
  isRequired,
  validate,
  defaultValue,
  disabled,
  readOnly,
  className,
  id,
  placeholder,
  rows,
}: FieldProps & { placeholder?: string; rows?: number }) => {
  const {
    id: inputId,
    field,
    fieldState,
    isRequired: required,
  } = useInput({ source, label, validate, defaultValue, isRequired, id });

  return (
    <UntitledTextArea
      id={inputId}
      className={cx("uu-scope", className)}
      name={field.name}
      textAreaRef={field.ref}
      label={label}
      placeholder={placeholder}
      rows={rows}
      value={
        typeof field.value === "string" ? field.value : String(field.value ?? "")
      }
      onChange={(value: string) => field.onChange(value)}
      onBlur={field.onBlur}
      validationBehavior="aria"
      isRequired={required}
      isDisabled={disabled ?? field.disabled}
      isReadOnly={readOnly}
      isInvalid={Boolean(fieldState.error)}
      hint={errorNode(fieldState.error) ?? hint}
    />
  );
};

export type FormChoice = { id: string; name: string };

export const FormSelect = ({
  source,
  label,
  hint,
  isRequired,
  validate,
  defaultValue,
  disabled,
  className,
  id,
  choices,
  placeholder,
}: FieldProps & { choices: FormChoice[]; placeholder?: string }) => {
  const {
    id: inputId,
    field,
    fieldState,
    isRequired: required,
  } = useInput({ source, label, validate, defaultValue, isRequired, id });
  const items: SelectItemType[] = choices.map((choice) => ({
    id: choice.id,
    label: choice.name,
  }));
  const selected = field.value == null ? null : String(field.value);

  return (
    <UntitledSelect
      id={inputId}
      className={cx("uu-scope", className)}
      label={label}
      placeholder={placeholder}
      items={items}
      selectedKey={selected === "" ? null : selected}
      onSelectionChange={(key) => {
        if (key !== null) field.onChange(String(key));
      }}
      onBlur={field.onBlur}
      ref={field.ref}
      name={field.name}
      validationBehavior="aria"
      isRequired={required}
      isDisabled={disabled ?? field.disabled}
      isInvalid={Boolean(fieldState.error)}
      hint={errorNode(fieldState.error) ?? hint}
    >
      {(item: SelectItemType) => (
        <UntitledSelect.Item id={item.id} label={item.label} />
      )}
    </UntitledSelect>
  );
};

export const FormToggle = ({
  source,
  label,
  hint,
  defaultValue,
  disabled,
  className,
  id,
}: FieldProps) => {
  const { id: inputId, field, fieldState } = useInput({
    source,
    label,
    defaultValue,
    id,
  });

  return (
    <FormFieldRow
      label={label}
      htmlFor={inputId}
      hint={hint}
      error={errorNode(fieldState.error)}
      className={className}
    >
      <UntitledToggle
        id={inputId}
        name={field.name}
        className="uu-scope"
        aria-label={label}
        isSelected={field.value === true}
        isDisabled={disabled ?? field.disabled}
        onChange={(isSelected: boolean) => field.onChange(isSelected)}
        onBlur={field.onBlur}
      />
    </FormFieldRow>
  );
};

export const FormCheckbox = ({
  source,
  label,
  hint,
  defaultValue,
  disabled,
  className,
  id,
}: FieldProps) => {
  const { id: inputId, field, fieldState } = useInput({
    source,
    label,
    defaultValue,
    id,
  });

  return (
    <UntitledCheckbox
      id={inputId}
      className={cx("uu-scope", className)}
      name={field.name}
      ref={field.ref}
      label={label}
      isSelected={field.value === true}
      isDisabled={disabled ?? field.disabled}
      onChange={(isSelected: boolean) => field.onChange(isSelected)}
      onBlur={field.onBlur}
      validationBehavior="aria"
      isInvalid={Boolean(fieldState.error)}
      hint={errorNode(fieldState.error) ?? hint}
    />
  );
};
