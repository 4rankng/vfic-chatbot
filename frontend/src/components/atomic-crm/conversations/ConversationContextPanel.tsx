import { useMemo, useState } from "react";
import { useTranslate } from "ra-core";
import { useIsMobile } from "@/hooks/use-mobile";
import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { CloseButton } from "@/components/base/buttons/close-button";
import { ProgressBar } from "@/components/base/progress-indicators/progress-indicators";
import { InputBase, TextField } from "@/components/base/input/input";
import { Label } from "@/components/base/input/label";
import { TextArea } from "@/components/base/textarea/textarea";
import {
  Dialog,
  Modal,
  ModalOverlay,
} from "@/components/application/slideout-menus/slideout-menu";
import type { Lead } from "../types";
import {
  candidateProfileDraft,
  candidateProfileFields,
  changedCandidateProfileValues,
  type CandidateProfileDraft,
  type CandidateProfileUpdate,
} from "../leads/domain/candidateProfile";
import { formatCandidateNotes } from "./domain/candidate-notes";
import {
  BusFront,
  CalendarDays,
  Check,
  CircleDollarSign,
  FileBadge,
  Handshake,
  Home,
  LoaderCircle,
  MapPin,
  NotepadText,
  Pencil,
  Phone,
  Save,
  UserRound,
  X,
  type LucideIcon,
} from "lucide-react";

const display = (value: unknown, fallback: string) => {
  if (value === undefined || value === null) return fallback;
  const text = String(value).trim();
  return text || fallback;
};

type CandidateInfoItem = {
  key: string;
  label: string;
  value: string;
  noteItems?: string[];
  complete: boolean;
  Icon: LucideIcon;
};

const hasMeaningfulValue = (value: unknown) => display(value, "") !== "";

const notesInclude = (notes: string | null | undefined, terms: string[]) => {
  const normalized = notes?.toLocaleLowerCase("vi-VN") ?? "";
  return terms.some((term) => normalized.includes(term));
};

export const ConversationContextPanel = ({
  lead,
  open,
  persistent = false,
  canEdit = false,
  onSave,
  onClose,
  onCloseAutoFocus,
}: {
  lead?: Lead;
  open: boolean;
  persistent?: boolean;
  canEdit?: boolean;
  onSave?: (
    changes: Partial<CandidateProfileUpdate>,
    version: number,
  ) => Promise<void>;
  onClose: () => void;
  onCloseAutoFocus?: (event: Event) => void;
}) => {
  const isMobile = useIsMobile();
  const translate = useTranslate();
  const candidateInfoItems = useMemo<CandidateInfoItem[]>(() => {
    const noData = translate("crm.common.no_data");
    const notes = lead?.notes;
    const noteItems = formatCandidateNotes(notes);
    const dateOfBirth = lead?.birth_year
      ? String(lead.birth_year)
      : lead?.age
        ? `${lead.age} tuổi`
        : "";
    const area = [lead?.region, lead?.living_area].filter(Boolean).join(" · ");
    const hasCitizenId = notesInclude(notes, ["cccd", "cmnd", "căn cước"]);
    const hasHousing = notesInclude(notes, [
      "chỗ ở",
      "cho o",
      "nhà trọ",
      "nha tro",
      "ký túc",
      "ky tuc",
      "ktx",
    ]);
    const hasPickup = notesInclude(notes, [
      "đưa đón",
      "dua don",
      "xe đưa",
      "xe dua",
      "xe đón",
      "xe don",
      "bus",
      "tuyến xe",
      "tuyen xe",
    ]);

    return [
      {
        key: "name",
        label: translate("leads.fields.name"),
        value: display(lead?.name, noData),
        complete: hasMeaningfulValue(lead?.name),
        Icon: UserRound,
      },
      {
        key: "phone",
        label: translate("leads.fields.phone"),
        value: display(lead?.phone, noData),
        complete: hasMeaningfulValue(lead?.phone),
        Icon: Phone,
      },
      {
        key: "birth",
        label: translate("leads.fields.date_of_birth"),
        value: display(dateOfBirth, noData),
        complete: Boolean(dateOfBirth),
        Icon: CalendarDays,
      },
      {
        key: "citizen-id",
        label: translate("leads.fields.citizen_id"),
        value: hasCitizenId
          ? translate("leads.recorded_in_notes")
          : translate("leads.needs_follow_up"),
        complete: hasCitizenId,
        Icon: FileBadge,
      },
      {
        key: "experience",
        label: translate("leads.fields.experience"),
        value: display(lead?.years_experience, noData),
        complete: hasMeaningfulValue(lead?.years_experience),
        Icon: FileBadge,
      },
      {
        key: "expectation",
        label: translate("leads.fields.expectation"),
        value: display(lead?.desired_job, noData),
        complete: hasMeaningfulValue(lead?.desired_job),
        Icon: Handshake,
      },
      {
        key: "salary",
        label: translate("leads.fields.salary"),
        value: display(lead?.expected_salary, noData),
        complete: hasMeaningfulValue(lead?.expected_salary),
        Icon: CircleDollarSign,
      },
      {
        key: "housing",
        label: translate("leads.fields.housing"),
        value: hasHousing
          ? translate("leads.recorded_in_notes")
          : translate("leads.needs_follow_up"),
        complete: hasHousing,
        Icon: Home,
      },
      {
        key: "pickup",
        label: translate("leads.fields.pickup"),
        value: hasPickup
          ? translate("leads.recorded_in_notes")
          : translate("leads.needs_follow_up"),
        complete: hasPickup,
        Icon: BusFront,
      },
      {
        key: "area",
        label: translate("leads.fields.area"),
        value: display(area, noData),
        complete: Boolean(area),
        Icon: MapPin,
      },
      {
        key: "address",
        label: translate("leads.fields.address"),
        value: display(lead?.address, noData),
        complete: hasMeaningfulValue(lead?.address),
        Icon: Home,
      },
      {
        key: "notes",
        label: translate("leads.fields.notes"),
        value:
          noteItems.length > 0 ? noteItems.join("\n") : display(null, noData),
        noteItems: noteItems.length > 0 ? noteItems : undefined,
        complete: noteItems.length > 0,
        Icon: NotepadText,
      },
    ];
  }, [lead, translate]);
  const completedInfoCount = candidateInfoItems.filter(
    (item) => item.complete,
  ).length;
  const completionPercent =
    candidateInfoItems.length > 0
      ? Math.round((completedInfoCount / candidateInfoItems.length) * 100)
      : 0;
  const content = (
    <CandidateContextBody
      key={String(lead?.id ?? "empty")}
      lead={lead}
      candidateInfoItems={candidateInfoItems}
      completedInfoCount={completedInfoCount}
      completionPercent={completionPercent}
      canEdit={canEdit}
      onSave={onSave}
      closeButtonPress={isMobile ? undefined : onClose}
      showClose={!persistent}
    />
  );

  if (isMobile) {
    return (
      <ModalOverlay
        isOpen={open}
        onOpenChange={(nextOpen) => {
          if (nextOpen) return;
          // Preserve the caller's focus contract: the console wants focus back
          // on the trigger that opened the panel, which the dialog cannot know.
          onCloseAutoFocus?.(new Event("modal-close-autofocus"));
          onClose();
        }}
        isDismissable
        className="z-50"
      >
        <Modal>
          <Dialog
            id="conversation-context-panel"
            aria-label={translate("leads.profile_title")}
            className="candidate-context-sheet uu-scope flex flex-col gap-0 p-0 outline-hidden"
          >
            <div className="inbox-bg-container conversation-context-sheet-body">
              {content}
            </div>
          </Dialog>
        </Modal>
      </ModalOverlay>
    );
  }

  return (
    <aside
      id="conversation-context-panel"
      className={`panel right-panel ${open ? "context-open" : ""} ${persistent ? "context-persistent" : ""}`}
      aria-label={translate("leads.profile_title")}
      aria-hidden={!open}
    >
      {content}
    </aside>
  );
};

const CandidateContextBody = ({
  lead,
  candidateInfoItems,
  completedInfoCount,
  completionPercent,
  canEdit,
  onSave,
  closeButtonPress,
  showClose,
}: {
  lead?: Lead;
  candidateInfoItems: CandidateInfoItem[];
  completedInfoCount: number;
  completionPercent: number;
  canEdit: boolean;
  onSave?: (
    changes: Partial<CandidateProfileUpdate>,
    version: number,
  ) => Promise<void>;
  /**
   * Called by the visible close button. Mobile renders the body inside a React
   * Aria dialog, where the button's `slot="close"` already closes the modal and
   * the overlay's `onOpenChange` notifies the owner — passing a handler there
   * would notify twice.
   */
  closeButtonPress?: () => void;
  showClose: boolean;
}) => {
  const [editSession, setEditSession] = useState<{
    initial: CandidateProfileDraft;
    draft: CandidateProfileDraft;
    version: number;
  } | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const translate = useTranslate();

  const cancelEditing = () => {
    if (isSaving) return;
    setEditSession(null);
  };

  const saveProfile = async () => {
    if (!editSession || !onSave || isSaving) return;
    const changes = changedCandidateProfileValues(
      editSession.initial,
      editSession.draft,
    );
    if (Object.keys(changes).length === 0) {
      setEditSession(null);
      return;
    }
    setIsSaving(true);
    try {
      await onSave(changes, editSession.version);
      setEditSession(null);
    } catch {
      // The capability adapter owns the user-facing notification and refetch.
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <>
      <header className="profile-header">
        <div className="profile-title">
          <UserRound className="icon" aria-hidden="true" />
          <span className="profile-title-copy">
            <span>{display(lead?.name, translate("leads.fallback_name"))}</span>
            <small>{display(lead?.phone, translate("leads.no_phone"))}</small>
          </span>
        </div>
        {showClose ? (
          <div className="context-header-actions">
            <CloseButton
              size="sm"
              className="uu-scope context-close"
              label="Đóng thông tin ứng viên"
              onPress={closeButtonPress}
            />
          </div>
        ) : null}
      </header>

      <div className="profile-scroll">
        <section className="context-overview candidate-progress-card tt-card tt-card-sm">
          <div className="candidate-progress-top">
            <span className="context-overview-kicker">
              Thông tin đã thu thập
            </span>
            <Badge
              type="pill-color"
              color="brand"
              size="sm"
              className="uu-scope candidate-progress-score tt-badge tt-badge-soft"
            >
              {completedInfoCount}/{candidateInfoItems.length}
            </Badge>
          </div>
          {/* Decorative: the paragraph below states the same completion in
              words, so the meter stays out of the accessible tree instead of
              announcing an unnamed progressbar twice. */}
          <div aria-hidden="true">
            <ProgressBar
              value={completionPercent}
              className="candidate-progress-meter"
              progressClassName="candidate-progress-fill"
            />
          </div>
          <p>
            Đã thu thập {completionPercent}% thông tin cần cho tư vấn tuyển
            dụng.
          </p>
        </section>
        <section className="context-card tt-card tt-card-sm">
          <div className="section-head">
            <h3>{translate("leads.profile_title")}</h3>
            {canEdit &&
            lead &&
            lead.version != null &&
            onSave &&
            !editSession ? (
              <Button
                type="button"
                size="xs"
                color="tertiary"
                className="uu-scope"
                aria-label="Chỉnh sửa hồ sơ ứng viên"
                iconLeading={<Pencil className="size-3.5" aria-hidden="true" />}
                onPress={() => {
                  if (lead.version == null) return;
                  const initial = candidateProfileDraft(lead);
                  setEditSession({
                    initial,
                    draft: { ...initial },
                    version: lead.version,
                  });
                }}
              >
                Sửa
              </Button>
            ) : null}
          </div>
          {editSession ? (
            <form
              className="grid gap-4"
              onSubmit={(event) => {
                event.preventDefault();
                void saveProfile();
              }}
            >
              <div className="grid gap-3 sm:grid-cols-2">
                {candidateProfileFields.map((field) => {
                  const inputId = `candidate-profile-${field.key}`;
                  return (
                    <TextField
                      key={field.key}
                      id={inputId}
                      className="min-w-0"
                      value={editSession.draft[field.key]}
                      isDisabled={isSaving}
                      onChange={(next) =>
                        setEditSession((current) =>
                          current
                            ? {
                                ...current,
                                draft: { ...current.draft, [field.key]: next },
                              }
                            : current,
                        )
                      }
                    >
                      <Label>{translate(field.labelKey)}</Label>
                      <InputBase
                        inputMode={field.inputMode}
                        type={field.inputMode === "numeric" ? "number" : "text"}
                        min={field.min}
                        max={field.max}
                      />
                    </TextField>
                  );
                })}
              </div>
              <TextArea
                id="candidate-profile-notes"
                label="Ghi chú (CCCD, chỗ ở, xe đưa đón và thông tin khác)"
                value={editSession.draft.notes}
                rows={5}
                isDisabled={isSaving}
                onChange={(next) =>
                  setEditSession((current) =>
                    current
                      ? { ...current, draft: { ...current.draft, notes: next } }
                      : current,
                  )
                }
              />
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  type="button"
                  size="sm"
                  color="secondary"
                  className="uu-scope"
                  isDisabled={isSaving}
                  iconLeading={<X className="size-4" aria-hidden="true" />}
                  onPress={cancelEditing}
                >
                  {translate("ra.action.cancel")}
                </Button>
                <Button
                  type="submit"
                  size="sm"
                  color="primary"
                  className="uu-scope"
                  isDisabled={isSaving}
                  iconLeading={
                    isSaving ? (
                      <LoaderCircle
                        className="size-4 animate-spin motion-reduce:animate-none"
                        aria-hidden="true"
                      />
                    ) : (
                      <Save className="size-4" aria-hidden="true" />
                    )
                  }
                >
                  {isSaving
                    ? translate("crm.common.saving")
                    : translate("crm.common.save_changes")}
                </Button>
              </div>
            </form>
          ) : (
            <div className="candidate-info-grid">
              {candidateInfoItems.map((item) => (
                <CandidateInfoRow key={item.key} item={item} />
              ))}
            </div>
          )}
        </section>
      </div>
    </>
  );
};

const CandidateInfoRow = ({ item }: { item: CandidateInfoItem }) => {
  const Icon = item.Icon;

  return (
    <div
      className={`candidate-info-row ${item.complete ? "filled" : ""}`}
      data-field={item.key}
    >
      <span className="candidate-info-icon">
        <Icon className="icon" aria-hidden="true" />
      </span>
      <div className="candidate-info-copy">
        <span className="candidate-info-label">{item.label}</span>
        {item.noteItems ? (
          <ul className="candidate-info-value candidate-note-list">
            {item.noteItems.map((note, index) => (
              <li key={`${index}-${note}`}>{note}</li>
            ))}
          </ul>
        ) : (
          <span className="candidate-info-value">{item.value}</span>
        )}
      </div>
      <span className="candidate-info-state" aria-hidden="true">
        {item.complete ? <Check className="icon" /> : null}
      </span>
    </div>
  );
};
