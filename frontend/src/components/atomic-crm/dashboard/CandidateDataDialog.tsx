import {
  CalendarDays,
  CircleDollarSign,
  FileBadge,
  Handshake,
  Home,
  MapPin,
  NotepadText,
  Pencil,
  Phone,
  Save,
  UserRound,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState, type RefObject } from "react";
import { useTranslate, type TranslateFunction } from "ra-core";

import {
  Dialog,
  Modal,
  ModalOverlay,
} from "@/components/application/modals/modal";
import { Avatar } from "@/components/base/avatar/avatar";
import { Button } from "@/components/base/buttons/button";
import { CloseButton } from "@/components/base/buttons/close-button";
import { InputBase, TextField } from "@/components/base/input/input";
import { Label } from "@/components/base/input/label";
import { TextArea } from "@/components/base/textarea/textarea";

import { formatCandidateNotes } from "../conversations/domain/candidate-notes";
import {
  candidateProfileDraft,
  candidateProfileFields,
  changedCandidateProfileValues,
  type CandidateProfileDraft,
  type CandidateProfileUpdate,
} from "../leads/domain/candidateProfile";
import type { Lead } from "../types";
import "./dashboard.css";

type CandidateDataDialogProps = {
  lead: Lead;
  displayName: string;
  displayAvatarUrl?: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
  canEdit: boolean;
  onSave: (
    changes: Partial<CandidateProfileUpdate>,
    version: number,
  ) => Promise<void>;
};

type ProfileField = {
  key: string;
  label: string;
  value: string;
  complete: boolean;
  Icon: LucideIcon;
  wide?: boolean;
};

const textValue = (value: unknown): string => String(value ?? "").trim();

const candidateFields = (
  lead: Lead,
  translate: TranslateFunction,
): ProfileField[] => {
  const birthOrAge = lead.birth_year
    ? String(lead.birth_year)
    : lead.age
      ? `${lead.age} tuổi`
      : "";
  const area = [lead.region, lead.living_area]
    .map(textValue)
    .filter(Boolean)
    .join(" · ");
  const notes = formatCandidateNotes(lead.notes);

  const field = (
    key: string,
    label: string,
    rawValue: unknown,
    Icon: LucideIcon,
    wide = false,
  ): ProfileField => {
    const value = textValue(rawValue);
    return {
      key,
      label,
      value: value || translate("crm.common.no_data"),
      complete: Boolean(value),
      Icon,
      wide,
    };
  };

  return [
    field("phone", translate("leads.fields.phone"), lead.phone, Phone),
    field("name", translate("leads.fields.name"), lead.name, UserRound),
    field(
      "desired-job",
      translate("leads.fields.desired_job"),
      lead.desired_job,
      Handshake,
    ),
    field(
      "birth",
      translate("leads.fields.birth_year_and_age"),
      birthOrAge,
      CalendarDays,
    ),
    field("gender", translate("leads.fields.gender"), lead.gender, UserRound),
    field(
      "experience",
      translate("leads.fields.experience"),
      lead.years_experience,
      FileBadge,
    ),
    field(
      "salary",
      translate("leads.fields.expected_salary"),
      lead.expected_salary,
      CircleDollarSign,
    ),
    field("area", translate("leads.fields.area"), area, MapPin),
    field(
      "address",
      translate("leads.fields.address"),
      lead.address,
      Home,
      true,
    ),
    field(
      "notes",
      translate("leads.fields.notes"),
      notes.length > 0 ? notes.join(" · ") : "",
      NotepadText,
      true,
    ),
  ];
};

/**
 * Candidate profile sheet, rendered on Untitled UI's dialog anatomy.
 *
 * The whole surface is one React Aria subtree (`ModalOverlay` → `Modal` →
 * `Dialog`, with React Aria fields and buttons inside), so no Radix
 * (`@/components/ui/**`) primitive is nested in it. `uu-scope` rides the
 * overlay because React Aria portals the modal to `document.body`, outside the
 * dashboard's own scope: without it the library's `bg-primary`/`text-primary`
 * would resolve to the console's coral action colour.
 */
export const CandidateDataDialog = ({
  lead,
  displayName,
  displayAvatarUrl,
  open,
  onOpenChange,
  returnFocusRef,
  canEdit,
  onSave,
}: CandidateDataDialogProps) => {
  const [editSession, setEditSession] = useState<{
    initial: CandidateProfileDraft;
    draft: CandidateProfileDraft;
    version: number;
  } | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const translate = useTranslate();
  const fields = candidateFields(lead, translate);
  const candidateName =
    textValue(displayName) ||
    textValue(lead.name) ||
    translate("leads.fallback_name");
  const candidatePhone = textValue(lead.phone) || translate("leads.no_phone");
  const pendingChanges = editSession
    ? changedCandidateProfileValues(editSession.initial, editSession.draft)
    : {};
  const hasChanges = Object.keys(pendingChanges).length > 0;

  useEffect(() => {
    if (!open) {
      setEditSession(null);
      setSaveError(null);
    }
  }, [lead.id, open]);

  const startEditing = () => {
    if (lead.version == null) return;
    const initial = candidateProfileDraft(lead);
    setSaveError(null);
    setEditSession({
      initial,
      draft: { ...initial },
      version: lead.version,
    });
  };

  const cancelEditing = () => {
    if (isSaving) return;
    setEditSession(null);
    setSaveError(null);
  };

  const saveProfile = async () => {
    if (!editSession || isSaving || !hasChanges) return;
    setIsSaving(true);
    setSaveError(null);
    try {
      await onSave(pendingChanges, editSession.version);
      setEditSession(null);
    } catch (error) {
      setSaveError(
        error instanceof Error
          ? error.message
          : "Không thể lưu thay đổi. Vui lòng thử lại.",
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleOpenChange = (nextOpen: boolean) => {
    // A save in flight owns the dialog: the close button, Escape and an outside
    // click all reach here, and each one must be a no-op until it settles.
    if (!nextOpen && isSaving) return;
    if (!nextOpen) returnFocusRef.current?.focus();
    onOpenChange(nextOpen);
  };

  return (
    <ModalOverlay
      isOpen={open}
      onOpenChange={handleOpenChange}
      isDismissable={!isSaving}
      isKeyboardDismissDisabled={isSaving}
      className="uu-scope"
    >
      <Modal className="w-full outline-hidden sm:max-w-2xl">
        <Dialog
          aria-label={translate("leads.profile_title")}
          className="candidate-data-dialog console-form-control flex flex-col gap-0 p-0 outline-hidden"
        >
          <header className="sticky top-0 z-10 border-b border-secondary bg-primary px-5 py-4 pr-14 text-left sm:px-6 sm:py-5">
            <div className="flex min-w-0 items-center gap-3">
              <Avatar
                size="lg"
                src={displayAvatarUrl ?? lead.avatar_url}
                alt={`Ảnh đại diện của ${candidateName}`}
              />
              <div className="min-w-0">
                <h2 className="truncate text-left text-lg font-semibold text-primary">
                  {translate("leads.profile_title")}
                </h2>
                <p className="mt-1 truncate text-left text-sm text-tertiary">
                  {candidateName} · {candidatePhone}
                </p>
              </div>
            </div>
            <CloseButton
              size="sm"
              slot={null}
              label={translate("ra.action.close")}
              isDisabled={isSaving}
              onPress={() => handleOpenChange(false)}
              className="absolute top-3 right-3"
            />
          </header>

          <div className="px-5 py-5 sm:px-6">
            <section
              className="rounded-lg border border-secondary bg-secondary p-4"
              aria-labelledby="candidate-completion-title"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3
                    id="candidate-completion-title"
                    className="text-sm font-semibold text-primary"
                  >
                    Liên hệ ứng viên
                  </h3>
                  <p className="mt-1 text-xs text-tertiary">
                    {lead.phone?.trim()
                      ? "Đã có số điện thoại để liên hệ."
                      : "Cần bổ sung số điện thoại để liên hệ."}{" "}
                    Họ tên được khuyến khích; nguyện vọng và năm sinh có thể bổ
                    sung sau.
                  </p>
                </div>
              </div>
            </section>

            <section
              className="mt-6"
              aria-labelledby="candidate-profile-fields-title"
            >
              <div className="flex min-h-9 items-center justify-between gap-3">
                <h3
                  id="candidate-profile-fields-title"
                  className="text-sm font-semibold text-primary"
                >
                  {editSession ? "Chỉnh sửa dữ liệu" : "Dữ liệu đã thu thập"}
                </h3>
                {canEdit && lead.version != null && !editSession ? (
                  <Button
                    type="button"
                    color="secondary"
                    size="sm"
                    iconLeading={Pencil}
                    onPress={startEditing}
                  >
                    Chỉnh sửa
                  </Button>
                ) : null}
              </div>

              {editSession ? (
                <form
                  className="candidate-data-form mt-3 grid gap-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void saveProfile();
                  }}
                >
                  <div className="candidate-data-fields grid gap-3 sm:grid-cols-2">
                    {[...candidateProfileFields]
                      .sort((left, right) => {
                        const priority = [
                          "phone",
                          "name",
                          "desired_job",
                          "birth_year",
                        ];
                        const rank = (key: string) => {
                          const index = priority.indexOf(key);
                          return index < 0 ? priority.length : index;
                        };
                        return rank(left.key) - rank(right.key);
                      })
                      .map((field) => {
                        const inputId = `dashboard-candidate-${lead.id}-${field.key}`;
                        return (
                          <TextField
                            key={field.key}
                            id={inputId}
                            name={field.key}
                            className="min-w-0"
                            size="sm"
                            value={editSession.draft[field.key]}
                            isDisabled={isSaving}
                            onChange={(next) =>
                              setEditSession((current) =>
                                current
                                  ? {
                                      ...current,
                                      draft: {
                                        ...current.draft,
                                        [field.key]: next,
                                      },
                                    }
                                  : current,
                              )
                            }
                          >
                            <Label>{translate(field.labelKey)}</Label>
                            <InputBase
                              inputMode={field.inputMode}
                              type={
                                field.inputMode === "numeric"
                                  ? "number"
                                  : field.inputMode === "tel"
                                    ? "tel"
                                    : "text"
                              }
                              autoComplete={
                                field.key === "name"
                                  ? "name"
                                  : field.key === "phone"
                                    ? "tel"
                                    : "off"
                              }
                              min={field.min}
                              max={field.max}
                            />
                          </TextField>
                        );
                      })}
                  </div>

                  <TextArea
                    id={`dashboard-candidate-${lead.id}-notes`}
                    label={translate("leads.fields.notes")}
                    size="sm"
                    value={editSession.draft.notes}
                    rows={5}
                    isDisabled={isSaving}
                    placeholder="CCCD, chỗ ở, xe đưa đón và thông tin khác"
                    onChange={(next) =>
                      setEditSession((current) =>
                        current
                          ? {
                              ...current,
                              draft: { ...current.draft, notes: next },
                            }
                          : current,
                      )
                    }
                  />

                  {saveError ? (
                    <div role="alert">
                      <p className="rounded-lg border border-error_subtle bg-error-primary px-3 py-2 text-sm font-medium text-error-primary">
                        {saveError}
                      </p>
                    </div>
                  ) : null}

                  <div className="sticky bottom-0 flex flex-wrap justify-end gap-2 border-t border-secondary bg-primary pt-4">
                    <Button
                      type="button"
                      color="secondary"
                      size="sm"
                      iconLeading={X}
                      isDisabled={isSaving}
                      onPress={cancelEditing}
                    >
                      {translate("ra.action.cancel")}
                    </Button>
                    <Button
                      type="submit"
                      color="primary"
                      size="sm"
                      iconLeading={Save}
                      isLoading={isSaving}
                      showTextWhileLoading
                      isDisabled={isSaving || !hasChanges}
                    >
                      {isSaving
                        ? translate("crm.common.saving")
                        : translate("crm.common.save_changes")}
                    </Button>
                  </div>
                </form>
              ) : (
                <dl className="mt-2 grid grid-cols-1 sm:grid-cols-2 sm:gap-x-6">
                  {fields.map(({ key, label, value, complete, Icon, wide }) => (
                    <div
                      key={key}
                      className={`grid min-w-0 grid-cols-[20px_minmax(0,1fr)] gap-3 border-b border-secondary py-3.5 ${
                        wide ? "sm:col-span-2" : ""
                      }`}
                    >
                      <Icon
                        className="mt-0.5 size-4 text-quaternary"
                        aria-hidden="true"
                      />
                      <div className="min-w-0">
                        <dt className="text-xs font-medium text-tertiary">
                          {label}
                        </dt>
                        <dd
                          className={`mt-1 break-words text-sm ${
                            complete
                              ? "font-medium text-primary"
                              : "text-quaternary"
                          }`}
                        >
                          {value}
                        </dd>
                      </div>
                    </div>
                  ))}
                </dl>
              )}
            </section>
          </div>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
};
