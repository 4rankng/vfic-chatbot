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
  /**
   * One line of guidance under the control. Text, not a node: the library's
   * `Select` types its `hint` as a string, and keeping one shape across the
   * controls stops a node from silently rendering as `[object Object]` there.
   */
  hint?: string;
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
const FALLBACK_FIELD_ERROR = "Giá trị chưa hợp lệ.";

type FieldError = { message: string; args: Record<string, unknown> };

/**
 * Message and interpolation args from react-admin's error payload, or
 * `undefined` when the field has no error. Shared by the ReactNode path (most
 * primitives) and the string path (`Select` and the other primitives whose
 * `hint` prop is typed `string`), so the two cannot drift.
 */
const unwrapFieldError = (
  error: { message?: string } | undefined,
): FieldError | undefined => {
  if (!error) return undefined;

  const raw = error.message;
  if (!raw) return { message: FALLBACK_FIELD_ERROR, args: {} };
  if (!raw.startsWith(ERROR_PREFIX)) return { message: raw, args: {} };

  try {
    const parsed: unknown = JSON.parse(raw.slice(ERROR_PREFIX.length));

    // react-admin encodes the validator result two ways: a bare string
    // (`required("…")` becomes `@@react-admin@@"…"`) and an object carrying the
    // message plus its interpolation args (translated validators). Reading only
    // the object shape renders the fallback for the common case; reading only
    // the string shape renders the raw envelope.
    if (typeof parsed === "string") return { message: parsed, args: {} };

    if (parsed && typeof parsed === "object") {
      const message =
        "message" in parsed && typeof parsed.message === "string"
          ? parsed.message
          : FALLBACK_FIELD_ERROR;
      // `args` is react-admin's own interpolation map; the object check above is
      // the only shape guarantee the envelope gives.
      const args =
        "args" in parsed && parsed.args && typeof parsed.args === "object"
          ? (parsed.args as Record<string, unknown>)
          : {};

      return { message, args };
    }

    return { message: raw, args: {} };
  } catch {
    return { message: raw, args: {} };
  }
};

const FieldErrorText = ({ error }: { error: FieldError }) => {
  const translate = useTranslate();

  return <>{translate(error.message, { _: error.message, ...error.args })}</>;
};

const errorNode = (error: { message?: string } | undefined): ReactNode => {
  const unwrapped = unwrapFieldError(error);
  return unwrapped ? <FieldErrorText error={unwrapped} /> : undefined;
};

/** Same message as {@link errorNode}, as text, for `hint` props typed string. */
const useFieldErrorText = (
  error: { message?: string } | undefined,
): string | undefined => {
  const translate = useTranslate();
  const unwrapped = unwrapFieldError(error);

  return unwrapped
    ? translate(unwrapped.message, { _: unwrapped.message, ...unwrapped.args })
    : undefined;
};

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
  // Untitled UI's Select types `hint` as a string, so the error travels as text.
  const errorText = useFieldErrorText(fieldState.error);

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
      hint={errorText ?? hint}
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
