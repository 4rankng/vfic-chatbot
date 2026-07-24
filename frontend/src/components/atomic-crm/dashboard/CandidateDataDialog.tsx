import {
  CalendarDays,
  CircleDollarSign,
  FileBadge,
  Handshake,
  Home,
  MapPin,
  NotepadText,
  Phone,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import type { RefObject } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";

import { formatCandidateNotes } from "../conversations/candidateNotes";
import { LeadAvatar } from "../conversations/LeadAvatar";
import type { Lead } from "../types";

type CandidateDataDialogProps = {
  lead: Lead;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
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

const candidateFields = (lead: Lead): ProfileField[] => {
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
      value: value || "Chưa có dữ liệu",
      complete: Boolean(value),
      Icon,
      wide,
    };
  };

  return [
    field("name", "Họ tên", lead.name, UserRound),
    field("phone", "Số điện thoại", lead.phone, Phone),
    field("birth", "Năm sinh / tuổi", birthOrAge, CalendarDays),
    field("gender", "Giới tính", lead.gender, UserRound),
    field("desired-job", "Công việc mong muốn", lead.desired_job, Handshake),
    field("experience", "Kinh nghiệm", lead.years_experience, FileBadge),
    field(
      "salary",
      "Mức lương mong muốn",
      lead.expected_salary,
      CircleDollarSign,
    ),
    field("area", "Khu vực", area, MapPin),
    field("address", "Địa chỉ hiện tại", lead.address, Home, true),
    field(
      "notes",
      "Ghi chú",
      notes.length > 0 ? notes.join(" · ") : "",
      NotepadText,
      true,
    ),
  ];
};

export const CandidateDataDialog = ({
  lead,
  open,
  onOpenChange,
  returnFocusRef,
}: CandidateDataDialogProps) => {
  const fields = candidateFields(lead);
  const completedFields = fields.filter((field) => field.complete).length;
  const completionPercent = Math.round((completedFields / fields.length) * 100);
  const candidateName = textValue(lead.name) || "Ứng viên";
  const candidatePhone = textValue(lead.phone) || "Chưa có số điện thoại";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="flex max-h-[calc(100dvh-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          returnFocusRef.current?.focus();
        }}
      >
        <DialogHeader className="border-b border-border px-5 py-4 pr-14 text-left sm:px-6 sm:py-5">
          <div className="flex min-w-0 items-center gap-3">
            <LeadAvatar
              src={lead.avatar_url}
              alt={`Ảnh đại diện của ${candidateName}`}
              className="flex size-11 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground"
              iconSize={20}
            />
            <div className="min-w-0">
              <DialogTitle className="truncate text-left">
                Thông tin ứng viên
              </DialogTitle>
              <DialogDescription className="mt-1 truncate text-left">
                {candidateName} · {candidatePhone}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
          <section
            className="rounded-lg border border-border bg-muted/35 p-4"
            aria-labelledby="candidate-completion-title"
          >
            <div className="mb-3 flex items-start justify-between gap-4">
              <div>
                <h3
                  id="candidate-completion-title"
                  className="text-body font-semibold text-foreground"
                >
                  Mức độ hoàn thiện
                </h3>
                <p className="mt-1 text-helper text-muted-foreground">
                  Dữ liệu đã được thu thập trong quá trình tư vấn tuyển dụng.
                </p>
              </div>
              <span className="shrink-0 text-label font-semibold text-foreground">
                {completedFields}/{fields.length} mục
              </span>
            </div>
            <Progress
              value={completionPercent}
              aria-label={`Đã hoàn thiện ${completionPercent}% hồ sơ ứng viên`}
            />
          </section>

          <section
            className="mt-6"
            aria-labelledby="candidate-profile-fields-title"
          >
            <h3
              id="candidate-profile-fields-title"
              className="text-body font-semibold text-foreground"
            >
              Dữ liệu đã thu thập
            </h3>
            <dl className="mt-2 grid grid-cols-1 sm:grid-cols-2 sm:gap-x-6">
              {fields.map(({ key, label, value, complete, Icon, wide }) => (
                <div
                  key={key}
                  className={`grid min-w-0 grid-cols-[20px_minmax(0,1fr)] gap-3 border-b border-border py-3.5 ${
                    wide ? "sm:col-span-2" : ""
                  }`}
                >
                  <Icon
                    className="mt-0.5 size-4 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <div className="min-w-0">
                    <dt className="text-helper font-medium text-muted-foreground">
                      {label}
                    </dt>
                    <dd
                      className={`mt-1 break-words text-body ${
                        complete
                          ? "font-medium text-foreground"
                          : "text-muted-foreground"
                      }`}
                    >
                      {value}
                    </dd>
                  </div>
                </div>
              ))}
            </dl>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
};
