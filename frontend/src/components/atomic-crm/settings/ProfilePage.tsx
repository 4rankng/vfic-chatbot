import { useMutation } from "@tanstack/react-query";
import {
  CircleX,
  Globe2,
  LogOut,
  Pencil,
  Save,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import {
  Form,
  required,
  useGetIdentity,
  useGetOne,
  useInput,
  useLocaleState,
  useLocales,
  useLogout,
  useNotify,
  useRecordContext,
  useTranslate,
  ValidationError,
} from "ra-core";
import { useState } from "react";
import { useFormContext, useFormState } from "react-hook-form";
import { Button } from "@/components/base/buttons/button";
import { InputBase, TextField } from "@/components/base/input/input";
import { Label } from "@/components/base/input/label";
import { Select } from "@/components/base/select/select";
import type { SelectItemType } from "@/components/base/select/select-shared";
import { useIsMobile } from "@/hooks/use-mobile";
import { InboxIcons } from "../conversations/InboxIcons";
import { apiJson, ApiError } from "@/lib/apiClient";
import type { Profile } from "../types";
import "../conversations/inbox.css";

type ProfileFieldSource = "full_name" | "email";

// Self-profile edit. The signed-in user edits their own row in `profiles`
// (exposed as the "users" resource, which the dataProvider aliases to the
// profiles table). VFIC profiles carry a single `full_name` + `email` (no
// first/last split, no avatar column), so the form is a single name field.
export const ProfilePage = () => {
  const [isEditMode, setEditMode] = useState(false);
  const { identity, refetch: refetchIdentity } = useGetIdentity();
  const profileId = identity?.id != null ? String(identity.id) : undefined;
  const { data, refetch: refetchUser } = useGetOne<Profile>("users", {
    id: profileId,
  });
  const translate = useTranslate();
  const notify = useNotify();
  const isMobile = useIsMobile();

  const { isPending, mutate } = useMutation({
    mutationKey: ["profile-update"],
    mutationFn: async (values: { full_name?: string; email?: string }) => {
      return apiJson<Record<string, unknown>>("/api/v1/users/me", {
        method: "PATCH",
        body: { full_name: values.full_name, email: values.email },
      });
    },
    onSuccess: () => {
      refetchIdentity();
      refetchUser();
      setEditMode(false);
      notify("crm.profile.updated");
    },
    onError: (error: Error) => {
      if (error instanceof ApiError && error.status === 409) {
        notify("Email đã được sử dụng bởi tài khoản khác", { type: "error" });
      } else {
        notify("crm.profile.update_error", { type: "error" });
      }
    },
  });

  if (!identity) return null;

  const handleOnSubmit = async (values: {
    full_name?: string;
    email?: string;
  }) => {
    mutate(values);
  };

  const displayName = data?.full_name?.trim() || translate("crm.profile.title");
  const displayEmail = data?.email?.trim() || "";

  const content = (
    <div className="profile-workspace-content text-foreground">
      <div className="ops-page-shell profile-page-shell">
        <header className="ops-command-header profile-command-header">
          <div className="ops-command-title">
            <div className="ops-command-mark profile-command-mark">
              <UserRound className="size-5" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <p className="ops-kicker">Tài khoản</p>
              <h1>Hồ sơ cá nhân</h1>
              <p>{[displayName, displayEmail].filter(Boolean).join(" · ")}</p>
            </div>
          </div>
        </header>

        <Form onSubmit={handleOnSubmit} record={data}>
          <ProfileForm
            isEditMode={isEditMode}
            isSaving={isPending}
            setEditMode={setEditMode}
          />
        </Form>
      </div>
    </div>
  );

  if (isMobile) {
    return <div className="profile-mobile-shell">{content}</div>;
  }

  return (
    <div className="inbox-bg-container profile-workspace">
      <InboxIcons />
      <div className="app profile-app" id="app">
        <section className="panel center-panel profile-center-panel">
          {content}
        </section>
      </div>
    </div>
  );
};

const ProfileForm = ({
  isEditMode,
  isSaving,
  setEditMode,
}: {
  isEditMode: boolean;
  isSaving: boolean;
  setEditMode: (value: boolean) => void;
}) => {
  const translate = useTranslate();
  const { identity } = useGetIdentity();
  const logout = useLogout();
  const { isDirty } = useFormState();
  const { reset } = useFormContext();

  if (!identity) return null;

  return (
    <div className="profile-grid">
      <section
        className="profile-section profile-account-section"
        aria-labelledby="profile-account-title"
      >
        <header className="profile-section-header">
          <div className="profile-section-heading">
            <span className="profile-card-icon">
              <ShieldCheck className="size-4" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <h2 id="profile-account-title">Thông tin tài khoản</h2>
              <p>Tên hiển thị và email đăng nhập.</p>
            </div>
          </div>
          <div className="profile-actions">
            {isEditMode ? (
              <>
                <Button
                  type="button"
                  color="tertiary"
                  className="uu-scope profile-action-button"
                  iconLeading={<CircleX />}
                  onClick={() => {
                    reset();
                    setEditMode(false);
                  }}
                >
                  {translate("ra.action.cancel")}
                </Button>
                <Button
                  type="submit"
                  color="primary"
                  className="uu-scope profile-action-button profile-save-button"
                  isDisabled={!isDirty || isSaving}
                  isLoading={isSaving}
                  showTextWhileLoading
                  iconLeading={isSaving ? undefined : <Save />}
                >
                  {isSaving
                    ? translate("crm.common.saving")
                    : translate("ra.action.save")}
                </Button>
              </>
            ) : (
              <Button
                type="button"
                color="secondary"
                className="uu-scope profile-action-button"
                iconLeading={<Pencil />}
                onClick={() => setEditMode(true)}
              >
                {translate("ra.action.edit")}
              </Button>
            )}
          </div>
        </header>

        <div className="profile-field-grid">
          <TextRender source="full_name" isEditMode={isEditMode} />
          <TextRender source="email" isEditMode={isEditMode} />
          <LanguageSelector />
        </div>
      </section>

      <section className="profile-session-section">
        <div className="profile-session-content">
          <div className="min-w-0">
            <h2>Đăng xuất</h2>
            <p>Kết thúc phiên trên thiết bị này.</p>
          </div>
          <Button
            type="button"
            color="secondary"
            className="uu-scope profile-action-button profile-logout-button"
            iconLeading={<LogOut className="size-4" />}
            onClick={() => logout()}
          >
            {translate("ra.auth.logout")}
          </Button>
        </div>
      </section>
    </div>
  );
};

const LanguageSelector = () => {
  const translate = useTranslate();
  const locales = useLocales();
  const [locale, setLocale] = useLocaleState();

  if (locales.length <= 1) {
    return null;
  }

  const items: SelectItemType[] = locales.map((language) => ({
    id: language.locale,
    label: language.name,
  }));

  return (
    <div className="profile-field">
      <div className="profile-field-label-row">
        <Globe2 className="size-3.5" aria-hidden="true" />
        <span className="profile-field-label">{translate("crm.language")}</span>
      </div>
      <Select
        aria-label={translate("crm.language")}
        className="uu-scope profile-select-trigger"
        items={items}
        selectedKey={locale}
        onSelectionChange={(key) => {
          if (key != null) setLocale(String(key));
        }}
      >
        {(item: SelectItemType) => (
          <Select.Item id={item.id} label={item.label} />
        )}
      </Select>
    </div>
  );
};

const TextRender = ({
  source,
  isEditMode,
  className,
}: {
  source: ProfileFieldSource;
  isEditMode: boolean;
  className?: string;
}) => {
  const translate = useTranslate();
  const record = useRecordContext<Profile>();
  const label = `resources.users.fields.${source}`;
  if (isEditMode) {
    return <ProfileTextField source={source} className={className} />;
  }
  return (
    <div className={`profile-field ${className ?? ""}`}>
      <span className="profile-field-label">
        {translate(label, { _: source })}
      </span>
      <span className="profile-field-value">
        {record?.[source]?.trim() || "Chưa cập nhật"}
      </span>
    </div>
  );
};

/**
 * Editable profile field on Untitled UI's `TextField` / `Label` / `InputBase`.
 *
 * `useInput` is react-admin's own hook, so the field registers, validates and
 * submits exactly like the `TextInput` it replaces — the screen swaps the
 * control, not the form engine. `validationBehavior="aria"` keeps React Aria's
 * default `native` behaviour from writing `required` onto the input and letting
 * the browser block the submit before react-admin validates.
 *
 * `uu-scope` and the console's `profile-*` classes both ride the control: the
 * wrapper re-binds the four utility names this console and Untitled UI both
 * define (`bg-primary`, `bg-secondary`, `text-primary`, `border-primary`), while
 * the profile sheet keeps owning the field's density. See
 * `src/styles/untitledui-theme.css`.
 */
const ProfileTextField = ({
  source,
  className,
}: {
  source: ProfileFieldSource;
  className?: string;
}) => {
  const translate = useTranslate();
  const label = `resources.users.fields.${source}`;
  const { id, field, fieldState, isRequired } = useInput({
    source,
    validate: required(),
  });
  const type = source === "email" ? "email" : "text";

  return (
    <TextField
      id={id}
      className={`profile-field profile-field-editing uu-scope ${className ?? ""}`}
      name={field.name}
      type={type}
      value={typeof field.value === "string" ? field.value : ""}
      onChange={(value: string) => field.onChange(value)}
      onBlur={field.onBlur}
      validationBehavior="aria"
      isRequired={isRequired}
      isInvalid={Boolean(fieldState.error)}
    >
      <Label className="profile-field-label">
        {translate(label, { _: source })}
      </Label>
      <InputBase
        ref={field.ref}
        type={type}
        autoComplete={source === "email" ? "email" : "name"}
        isInvalid={Boolean(fieldState.error)}
        wrapperClassName="profile-input"
      />
      {fieldState.error?.message ? (
        <p role="alert" className="text-helper text-[var(--workspace-danger)]">
          <ValidationError error={fieldState.error.message} />
        </p>
      ) : null}
    </TextField>
  );
};

ProfilePage.path = "/profile";
