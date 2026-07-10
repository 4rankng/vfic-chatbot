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
  useGetIdentity,
  useGetOne,
  useLocaleState,
  useLocales,
  useLogout,
  useNotify,
  useRecordContext,
  useTranslate,
} from "ra-core";
import { useState } from "react";
import { useFormState } from "react-hook-form";
import { TextInput } from "@/components/admin/text-input";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useIsMobile } from "@/hooks/use-mobile";
import { InboxIcons } from "../conversations/InboxIcons";
import { apiJson, ApiError } from "../providers/rest/api";
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

  const { mutate } = useMutation({
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
      notify("crm.profile.updated", {
        messageArgs: {
          _: "Thông tin đã được cập nhật",
        },
      });
    },
    onError: (error: Error) => {
      if (error instanceof ApiError && error.status === 409) {
        notify("Email đã được sử dụng bởi tài khoản khác", { type: "error" });
      } else {
        notify("crm.profile.update_error", {
          type: "error",
          messageArgs: {
            _: "Đã xảy ra lỗi. Vui lòng thử lại",
          },
        });
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
              <h1>{displayName}</h1>
              <p>
                {displayEmail ||
                  "Quản lý thông tin và tùy chọn tài khoản của bạn"}
              </p>
            </div>
          </div>
        </header>

        <Form onSubmit={handleOnSubmit} record={data}>
          <ProfileForm isEditMode={isEditMode} setEditMode={setEditMode} />
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
  setEditMode,
}: {
  isEditMode: boolean;
  setEditMode: (value: boolean) => void;
}) => {
  const translate = useTranslate();
  const { identity } = useGetIdentity();
  const logout = useLogout();
  const { isDirty } = useFormState();

  if (!identity) return null;

  return (
    <div className="profile-grid">
      <Card className="profile-card profile-account-card">
        <CardContent className="profile-card-content">
          <div className="profile-card-header">
            <span className="profile-card-icon">
              <ShieldCheck className="size-4" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <h2>Thông tin tài khoản</h2>
              <p>Cập nhật tên hiển thị, email và ngôn ngữ giao diện.</p>
            </div>
          </div>

          <div className="profile-field-grid">
            <TextRender source="full_name" isEditMode={isEditMode} />
            <TextRender source="email" isEditMode={isEditMode} />
            <LanguageSelector />
          </div>

          <div className="profile-actions">
            <Button
              type="button"
              variant={isEditMode ? "ghost" : "outline"}
              onClick={() => setEditMode(!isEditMode)}
              className="profile-action-button"
            >
              {isEditMode ? <CircleX /> : <Pencil />}
              {isEditMode
                ? translate("ra.action.cancel")
                : translate("ra.action.edit")}
            </Button>

            {isEditMode && (
              <Button
                type="submit"
                disabled={!isDirty}
                variant="outline"
                className="profile-action-button"
              >
                <Save />
                {translate("ra.action.save")}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Card className="profile-card profile-session-card">
        <CardContent className="profile-session-content">
          <div className="min-w-0">
            <h2>Đăng xuất</h2>
            <p>Thoát khỏi phiên làm việc trên thiết bị này.</p>
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={() => logout()}
            className="profile-action-button profile-logout-button"
          >
            <LogOut className="size-4" />
            {translate("ra.auth.logout")}
          </Button>
        </CardContent>
      </Card>
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

  return (
    <div className="profile-field">
      <div className="profile-field-label-row">
        <Globe2 className="size-3.5" aria-hidden="true" />
        <span className="profile-field-label">{translate("crm.language")}</span>
      </div>
      <Select value={locale} onValueChange={setLocale}>
        <SelectTrigger className="profile-select-trigger">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {locales.map((language) => (
            <SelectItem key={language.locale} value={language.locale}>
              {language.name}
            </SelectItem>
          ))}
        </SelectContent>
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
    return (
      <TextInput
        source={source}
        label={label}
        helperText={false}
        className={`profile-field profile-field-editing ${className ?? ""}`}
        inputClassName="profile-input"
      />
    );
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

ProfilePage.path = "/profile";
