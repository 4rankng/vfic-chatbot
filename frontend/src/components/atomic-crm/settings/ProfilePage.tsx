import { useMutation } from "@tanstack/react-query";
import { Check, CircleX, Copy, Pencil, Save } from "lucide-react";
import {
  Form,
  useDataProvider,
  useGetIdentity,
  useGetOne,
  useLocaleState,
  useLocales,
  useNotify,
  useTranslate,
} from "ra-core";
import { useState } from "react";
import { useFormState } from "react-hook-form";
import { RecordField } from "@/components/admin/record-field";
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import type { CrmDataProvider } from "../providers/types";
import type { Profile } from "../types";

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
  const dataProvider = useDataProvider<CrmDataProvider>();

  const { mutate } = useMutation({
    mutationKey: ["profile-update"],
    mutationFn: async (values: { full_name?: string; email?: string }) => {
      if (!identity || !data) {
        throw new Error(
          translate("crm.profile.record_not_found", {
            _: "Record not found",
          }),
        );
      }
      return dataProvider.update("users", {
        id: identity.id,
        data: { full_name: values.full_name, email: values.email },
        previousData: data,
      });
    },
    onSuccess: () => {
      refetchIdentity();
      refetchUser();
      setEditMode(false);
      notify("crm.profile.updated", {
        messageArgs: {
          _: "Your profile has been updated",
        },
      });
    },
    onError: () => {
      notify("crm.profile.update_error", {
        type: "error",
        messageArgs: {
          _: "An error occurred. Please try again",
        },
      });
    },
  });

  if (!identity) return null;

  const handleOnSubmit = async (values: {
    full_name?: string;
    email?: string;
  }) => {
    mutate(values);
  };

  return (
    <div className="max-w-lg mx-auto mt-6">
      <div className="mb-6 flex flex-col items-start border-b border-border pb-4">
        <h2 className="font-display text-4xl font-extrabold tracking-wide uppercase text-foreground">
          {translate("crm.profile.title")}
        </h2>
        <p className="text-muted-foreground text-xs font-medium mt-1">
          Quản lý thông tin và tùy chọn tài khoản của bạn
        </p>
      </div>
      <Form onSubmit={handleOnSubmit} record={data}>
        <ProfileForm isEditMode={isEditMode} setEditMode={setEditMode} />
      </Form>
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
  const { isDirty } = useFormState();

  if (!identity) return null;

  return (
    <div className="space-y-4">
      <Card className="border border-border bg-card shadow-xs hover:shadow-sm transition-all duration-300">
        <CardContent className="pt-6">
          <div className="mb-4 flex items-center gap-2">
            <span className="w-1.5 h-4.5 bg-primary rounded-full" />
            <span className="font-display text-lg font-bold tracking-wider uppercase text-foreground">
              Thông tin tài khoản
            </span>
          </div>

          <div className="space-y-4 mb-4">
            <TextRender source="full_name" isEditMode={isEditMode} />
            <TextRender source="email" isEditMode={isEditMode} />
            <LanguageSelector />
          </div>

          <div className="flex flex-row justify-end gap-2">
            <Button
              type="button"
              variant={isEditMode ? "ghost" : "outline"}
              onClick={() => setEditMode(!isEditMode)}
              className="flex items-center"
            >
              {isEditMode ? <CircleX /> : <Pencil />}
              {isEditMode
                ? translate("ra.action.cancel")
                : translate("ra.action.edit")}
            </Button>

            {isEditMode && (
              <Button type="submit" disabled={!isDirty} variant="outline">
                <Save />
                {translate("ra.action.save")}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
      {import.meta.env.VITE_INBOUND_EMAIL && (
        <Card className="border border-border bg-card shadow-xs hover:shadow-sm transition-all duration-300">
          <CardContent className="pt-6">
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-4.5 bg-primary rounded-full" />
                <span className="font-display text-lg font-bold tracking-wider uppercase text-foreground">
                  {translate("crm.profile.inbound.title")}
                </span>
              </div>
              <p className="text-sm text-muted-foreground">
                {translate("crm.profile.inbound.description", {
                  _: "You can start sending emails to your server's inbound email address, e.g. by adding it to the Cc: field. Atomic CRM will process the emails and add notes to the corresponding contacts.",
                  field: "Cc:",
                })}
              </p>
              <CopyPaste value={import.meta.env.VITE_INBOUND_EMAIL} />
            </div>
          </CardContent>
        </Card>
      )}
      <Card className="border border-border bg-card shadow-xs hover:shadow-sm transition-all duration-300">
        <CardContent className="pt-6">
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-4.5 bg-primary rounded-full" />
              <span className="font-display text-lg font-bold tracking-wider uppercase text-foreground">
                {translate("crm.profile.mcp.title", {
                  _: "MCP Server",
                })}
              </span>
            </div>
            <p className="text-sm text-muted-foreground">
              {translate("crm.profile.mcp.description", {
                _: "Use this URL to connect your AI assistant to your CRM data via the Model Context Protocol (MCP).",
              })}
            </p>
            <CopyPaste
              value={`${import.meta.env.VITE_SUPABASE_URL}/functions/v1/mcp`}
            />
          </div>
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
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        {translate("crm.language")}
      </p>
      <Select value={locale} onValueChange={setLocale}>
        <SelectTrigger className="w-full">
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
  source: string;
  isEditMode: boolean;
  className?: string;
}) => {
  const label = `resources.users.fields.${source}`;
  if (isEditMode) {
    return (
      <TextInput
        source={source}
        label={label}
        helperText={false}
        className={className}
      />
    );
  }
  return (
    <div className={className}>
      <RecordField source={source} label={label} />
    </div>
  );
};

const CopyPaste = ({ value }: { value: string }) => {
  const translate = useTranslate();
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    setCopied(true);
    navigator.clipboard.writeText(value);
    setTimeout(() => {
      setCopied(false);
    }, 1500);
  };
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            onClick={handleCopy}
            variant="ghost"
            className="normal-case justify-between w-full"
          >
            <span className="overflow-hidden text-ellipsis">{value}</span>
            {copied ? (
              <Check className="h-4 w-4 ml-2" />
            ) : (
              <Copy className="h-4 w-4 ml-2" />
            )}
          </Button>
        </TooltipTrigger>
        <TooltipContent>
          <p>
            {copied
              ? translate("crm.common.copied")
              : translate("crm.common.copy")}
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

ProfilePage.path = "/profile";
