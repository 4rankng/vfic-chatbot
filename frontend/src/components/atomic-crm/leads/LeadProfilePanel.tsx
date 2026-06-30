import { memo, useEffect, useRef, useState } from "react";
import { useDataProvider, useNotify, useRecordContext } from "ra-core";
import { apiJson } from "../providers/rest/api";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  LEAD_SCORES,
  LEAD_STAGES,
  type Conversation,
  type Lead,
} from "../types";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CheckCircle2, Pencil, Save, User, X } from "lucide-react";

type LeadProfilePanelProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Lead already loaded by the parent (looked up by zalo_id). When present
   *  the panel reuses it instead of firing a duplicate getList on every open. */
  lead?: Lead;
};

type LeadMemory = {
  id: string;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

const EDITABLE_FIELDS: Array<{
  field: keyof Lead;
  label: string;
  multiline?: boolean;
}> = [
  { field: "name", label: "Họ tên" },
  { field: "phone", label: "Số điện thoại" },
  { field: "desired_job", label: "Công việc mong muốn" },
  { field: "expected_salary", label: "Lương mong muốn" },
  { field: "region", label: "Tỉnh / thành" },
  { field: "living_area", label: "Khu vực sinh sống" },
  { field: "years_experience", label: "Kinh nghiệm" },
  { field: "notes", label: "Ghi chú", multiline: true },
];

const display = (value: unknown, fallback = "Chưa có dữ liệu") => {
  if (value === undefined || value === null) return fallback;
  const text = String(value).trim();
  return text || fallback;
};

const leadScoreLabel = (score: Lead["lead_score"]) =>
  LEAD_SCORES.find((item) => item.value === score)?.label ?? null;

const leadStageLabel = (stage: Lead["lead_stage"]) =>
  LEAD_STAGES.find((item) => item.value === stage)?.label ?? stage;

const profileRows = (lead: Lead) =>
  EDITABLE_FIELDS.map(({ field, label }) => ({
    label,
    value: lead[field],
  }));

const SYSTEM_ROWS: Array<{ label: string; key: keyof Lead }> = [
  { label: "Zalo ID", key: "zalo_id" },
];

const ProfileField = ({ label, value }: { label: string; value: unknown }) => (
  <div className="min-w-0 rounded-lg border border-border/70 bg-background px-3 py-3">
    <div className="text-[11px] font-semibold uppercase text-muted-foreground">
      {label}
    </div>
    <div
      className={`mt-1 break-words text-sm leading-relaxed ${
        value ? "text-foreground" : "text-muted-foreground"
      }`}
    >
      {display(value)}
    </div>
  </div>
);

const LeadProfilePanelImpl = ({
  open,
  onOpenChange,
  lead: leadProp,
}: LeadProfilePanelProps) => {
  const conversation = useRecordContext<Conversation>();
  const leadPropRef = useRef(leadProp);
  leadPropRef.current = leadProp;
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const [isEditing, setIsEditing] = useState(false);
  const [editData, setEditData] = useState<Partial<Lead>>({});
  const [isSaving, setIsSaving] = useState(false);
  // Transient override so the panel body reflects the save immediately,
  // even when the lead was supplied by a parent prop (query disabled).
  const [editedLead, setEditedLead] = useState<Lead | null>(null);

  const zaloChatId = conversation?.zalo_chat_id;

  // Lead lookup — skip when parent already provides the lead or panel is closed
  const { data: fetchedLead, isPending: isLeadPending } = useQuery({
    queryKey: ["lead-by-zalo", zaloChatId],
    queryFn: async () => {
      const result = await dataProvider.getList("leads", {
        filter: { zalo_id: zaloChatId },
        pagination: { page: 1, perPage: 1 },
        sort: { field: "updated_at", order: "DESC" },
      });
      return (result.data?.[0] as Lead) ?? null;
    },
    enabled: open && !!zaloChatId && !leadPropRef.current,
  });

  const lead = editedLead ?? leadProp ?? fetchedLead ?? null;
  const notFound =
    !isLeadPending && !!zaloChatId && !leadPropRef.current && !fetchedLead;

  // Memories lookup
  const { data: memoriesData, isPending: isMemoriesPending } = useQuery({
    queryKey: ["lead-memories", lead?.id],
    queryFn: () => apiJson<LeadMemory[]>(`/api/v1/leads/${lead!.id}/memories`),
    enabled: open && !!lead?.id,
  });

  const memories = memoriesData ?? [];
  const queryClient = useQueryClient();

  // Clear the transient save override when the query refetches (e.g. parent
  // navigates away and back, causing a new panel open that re-fetches).
  useEffect(() => {
    if (fetchedLead) setEditedLead(null);
  }, [fetchedLead]);

  if (!open) return null;

  const handleEditClick = () => {
    const next: Partial<Lead> = {};
    for (const { field } of EDITABLE_FIELDS) {
      next[field] = (lead?.[field] as never) ?? "";
    }
    setEditData(next);
    setIsEditing(true);
  };

  const handleSave = async () => {
    if (!lead) return;
    setIsSaving(true);
    try {
      const { data } = await dataProvider.update("leads", {
        id: lead.id,
        data: editData,
        previousData: lead,
      });
      setEditedLead(data as Lead);
      queryClient.setQueryData(["lead-by-zalo", zaloChatId], data as Lead);
      setIsEditing(false);
      notify("Đã cập nhật hồ sơ", { type: "success" });
    } catch {
      notify("Lỗi khi cập nhật hồ sơ", { type: "error" });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="fixed inset-0 left-0 top-0 flex h-[100dvh] w-screen max-w-none translate-x-0 translate-y-0 gap-0 overflow-hidden rounded-none border-0 bg-background p-0 text-foreground shadow-none sm:max-w-none [&>button]:hidden">
        <div className="flex min-h-0 w-full flex-col">
          <DialogHeader className="shrink-0 border-b border-border bg-background/95 px-4 py-3 text-left sm:px-6 lg:px-8">
            <div className="flex min-w-0 items-center justify-between gap-3">
              <DialogTitle className="flex min-w-0 items-center gap-3 text-lg font-bold text-foreground sm:text-xl">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border bg-muted">
                  <User className="size-5" />
                </span>
                <span className="min-w-0 truncate">Hồ sơ ứng viên</span>
              </DialogTitle>
              <DialogClose asChild>
                <button
                  type="button"
                  className="flex size-11 shrink-0 items-center justify-center rounded-lg border border-border bg-background text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                  aria-label="Đóng hồ sơ ứng viên"
                  title="Đóng"
                >
                  <X className="size-5" />
                </button>
              </DialogClose>
            </div>
          </DialogHeader>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {isLeadPending ? (
              <div className="mx-auto w-full max-w-7xl px-4 py-4 sm:px-6 lg:px-8 lg:py-6">
                <div className="rounded-lg border border-border bg-card p-5 text-sm text-muted-foreground">
                  Đang tải hồ sơ...
                </div>
              </div>
            ) : notFound || !lead ? (
              <div className="mx-auto w-full max-w-7xl px-4 py-4 sm:px-6 lg:px-8 lg:py-6">
                <div className="rounded-lg border border-border bg-card p-5 text-sm text-muted-foreground">
                  Chưa liên kết hồ sơ ứng viên
                </div>
              </div>
            ) : (
              <div className="mx-auto w-full max-w-6xl space-y-4 px-4 py-4 sm:space-y-5 sm:px-6 lg:px-8 lg:py-6">
                <section className="rounded-lg border border-border bg-card p-4 sm:p-5">
                  <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                    <div className="flex min-w-0 items-start gap-4">
                      <div className="flex size-14 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground sm:size-16">
                        <User className="size-7" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <h2 className="break-words text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
                          {display(lead.name, "Chưa rõ tên ứng viên")}
                        </h2>
                        <div className="mt-2 flex flex-wrap gap-2 text-sm text-muted-foreground">
                          {lead.lead_score ? (
                            <span className="rounded-md border border-border bg-muted px-2 py-1 font-medium">
                              {leadScoreLabel(lead.lead_score)}
                            </span>
                          ) : null}
                          {lead.lead_stage ? (
                            <span className="rounded-md border border-border bg-muted px-2 py-1 font-medium">
                              {leadStageLabel(lead.lead_stage)}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>

                    <div className="grid w-full grid-cols-2 gap-2 md:w-auto md:min-w-fit md:grid-cols-none md:flex md:justify-end">
                      {!isEditing ? (
                        <button
                          type="button"
                          onClick={handleEditClick}
                          className="col-span-2 inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 md:col-span-1 md:min-w-32"
                        >
                          <Pencil className="size-4" />
                          Chỉnh sửa
                        </button>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={handleSave}
                            disabled={isSaving}
                            className="inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60 md:min-w-32"
                          >
                            <Save className="size-4" />
                            {isSaving ? "Đang lưu..." : "Lưu hồ sơ"}
                          </button>
                          <button
                            type="button"
                            onClick={() => setIsEditing(false)}
                            disabled={isSaving}
                            className="inline-flex min-h-11 items-center justify-center whitespace-nowrap rounded-lg border border-border bg-background px-4 text-sm font-semibold text-foreground transition-colors hover:bg-muted focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60 md:min-w-28"
                          >
                            Hủy
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </section>

                <section className="rounded-lg border border-border bg-card p-4 sm:p-5">
                  <h3 className="text-lg font-semibold text-foreground">
                    {isEditing
                      ? "Chỉnh sửa thông tin tuyển dụng"
                      : "Thông tin tuyển dụng"}
                  </h3>
                  {!isEditing ? (
                    <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                      {profileRows(lead).map((row) => (
                        <ProfileField
                          key={row.label}
                          label={row.label}
                          value={row.value}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="mt-4 grid gap-4 sm:grid-cols-2">
                      {EDITABLE_FIELDS.map(({ field, label, multiline }) => (
                        <label
                          key={field}
                          className={`block min-w-0 ${multiline ? "sm:col-span-2" : ""}`}
                        >
                          <span className="text-[11px] font-semibold uppercase text-muted-foreground">
                            {label}
                          </span>
                          {multiline ? (
                            <textarea
                              className="mt-1 min-h-28 w-full resize-y rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/20"
                              value={(editData[field] as string | null) ?? ""}
                              onChange={(e) =>
                                setEditData({
                                  ...editData,
                                  [field]: e.target.value,
                                })
                              }
                              disabled={isSaving}
                            />
                          ) : (
                            <input
                              type="text"
                              className="mt-1 min-h-11 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/20"
                              value={(editData[field] as string | null) ?? ""}
                              onChange={(e) =>
                                setEditData({
                                  ...editData,
                                  [field]: e.target.value,
                                })
                              }
                              disabled={isSaving}
                            />
                          )}
                        </label>
                      ))}
                    </div>
                  )}
                </section>

                {!isEditing ? (
                  <section className="rounded-lg border border-border bg-card p-4 sm:p-5">
                    <h3 className="text-lg font-semibold text-foreground">
                      Thông tin hệ thống
                    </h3>
                    <div className="mt-4 grid gap-3 sm:grid-cols-2">
                      {SYSTEM_ROWS.map((row) => (
                        <ProfileField
                          key={row.key}
                          label={row.label}
                          value={lead[row.key]}
                        />
                      ))}
                    </div>
                  </section>
                ) : null}

                {lead.qualification_reasons?.length ? (
                  <section className="rounded-lg border border-border bg-card p-4 sm:p-5">
                    <h3 className="text-lg font-semibold text-foreground">
                      Lý do đánh giá
                    </h3>
                    <ul className="mt-4 grid gap-3 sm:grid-cols-2">
                      {lead.qualification_reasons.map((reason) => (
                        <li
                          key={reason}
                          className="flex gap-3 rounded-lg border border-border/70 bg-background px-3 py-3 text-sm leading-relaxed text-foreground"
                        >
                          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
                          <span>{reason}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}

                <section className="rounded-lg border border-border bg-card p-4 sm:p-5">
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="text-lg font-semibold text-foreground">
                      Ghi nhớ từ hội thoại
                    </h3>
                    <span className="shrink-0 rounded-md border border-border bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">
                      {isMemoriesPending
                        ? "Đang tải..."
                        : `${memories.length} mục`}
                    </span>
                  </div>
                  {isMemoriesPending ? (
                    <div className="mt-4 text-sm text-muted-foreground">
                      Đang tải ghi nhớ...
                    </div>
                  ) : memories.length ? (
                    <ul className="mt-4 grid gap-3 lg:grid-cols-2">
                      {memories.map((memory) => (
                        <li
                          key={memory.id}
                          className="rounded-lg border border-border/70 bg-background px-4 py-3 text-sm leading-relaxed text-foreground"
                        >
                          {memory.content}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="mt-4 text-sm text-muted-foreground">
                      Chưa có ghi nhớ nào cho ứng viên này.
                    </div>
                  )}
                </section>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export const LeadProfilePanel = memo(LeadProfilePanelImpl);
LeadProfilePanel.displayName = "LeadProfilePanel";
