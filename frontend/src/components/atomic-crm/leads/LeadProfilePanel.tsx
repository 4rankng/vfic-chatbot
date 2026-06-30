import { memo, useEffect, useRef, useState } from "react";
import { useDataProvider, useNotify, useRecordContext } from "ra-core";
import { apiJson } from "../providers/rest/api";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { Conversation, Lead } from "../types";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Briefcase,
  Building2,
  CheckCircle2,
  MapPin,
  Pencil,
  Phone,
  Save,
  User,
  X,
} from "lucide-react";

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

const EDITABLE_FIELDS: Array<keyof Lead> = [
  "name",
  "phone",
  "desired_job",
  "expected_salary",
  "living_area",
  "region",
  "latest_company",
  "notes",
];

const display = (value: unknown, fallback = "Chưa có dữ liệu") => {
  if (value === undefined || value === null) return fallback;
  const text = String(value).trim();
  return text || fallback;
};

const profileRows = (lead: Lead) => [
  { label: "Họ tên", value: lead.name },
  { label: "Số điện thoại", value: lead.phone },
  { label: "Zalo ID", value: lead.zalo_id },
  { label: "Công việc mong muốn", value: lead.desired_job },
  { label: "Lương mong muốn", value: lead.expected_salary },
  {
    label: "Khu vực",
    value: [lead.region, lead.living_area].filter(Boolean).join(" · "),
  },
  { label: "Công ty gần nhất", value: lead.latest_company },
  { label: "Kinh nghiệm", value: lead.years_experience },
  { label: "Ghi chú", value: lead.notes },
];

const profileHighlights = (lead: Lead) => [
  {
    label: "Điện thoại",
    value: lead.phone,
    fallback: "Chưa có số điện thoại",
    icon: Phone,
  },
  {
    label: "Công việc",
    value: lead.desired_job,
    fallback: "Chưa rõ công việc",
    icon: Briefcase,
  },
  {
    label: "Khu vực",
    value: [lead.region, lead.living_area].filter(Boolean).join(" · "),
    fallback: "Chưa rõ khu vực",
    icon: MapPin,
  },
  {
    label: "Công ty gần nhất",
    value: lead.latest_company,
    fallback: "Chưa có dữ liệu",
    icon: Building2,
  },
];

const editLabels: Record<string, string> = {
  name: "Họ tên",
  phone: "Số điện thoại",
  desired_job: "Công việc mong muốn",
  expected_salary: "Lương mong muốn",
  living_area: "Khu vực sinh sống",
  region: "Tỉnh / thành",
  latest_company: "Công ty gần nhất",
  notes: "Ghi chú nội bộ",
};

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
  const [lead, setLead] = useState<Lead | null>(null);
  const [memories, setMemories] = useState<LeadMemory[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingMemories, setIsLoadingMemories] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editData, setEditData] = useState<Partial<Lead>>({});
  const [isSaving, setIsSaving] = useState(false);

  const zaloChatId = conversation?.zalo_chat_id;

  useEffect(() => {
    if (!open) {
      setIsEditing(false);
      return;
    }
    if (!zaloChatId) {
      setLead(null);
      setNotFound(true);
      return;
    }

    const sharedLead = leadPropRef.current;
    if (sharedLead) {
      setLead(sharedLead);
      setNotFound(false);
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    setNotFound(false);
    (async () => {
      try {
        const { data } = await dataProvider.getList("leads", {
          filter: { zalo_id: zaloChatId },
          pagination: { page: 1, perPage: 1 },
          sort: { field: "updated_at", order: "DESC" },
        });
        if (cancelled) return;
        setLead((data?.[0] as Lead) ?? null);
        setNotFound(!data?.[0]);
      } catch {
        if (cancelled) return;
        setLead(null);
        setNotFound(true);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [dataProvider, zaloChatId, open]);

  useEffect(() => {
    if (!open || !lead?.id) {
      setMemories([]);
      return;
    }

    let cancelled = false;
    setIsLoadingMemories(true);
    apiJson<LeadMemory[]>(`/api/v1/leads/${lead.id}/memories`)
      .then((rows) => {
        if (!cancelled) setMemories(rows);
      })
      .catch(() => {
        if (!cancelled) setMemories([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingMemories(false);
      });
    return () => {
      cancelled = true;
    };
  }, [lead?.id, open]);

  if (!open) return null;

  const handleEditClick = () => {
    const next: Partial<Lead> = {};
    for (const field of EDITABLE_FIELDS) {
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
      setLead(data as Lead);
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
            {isLoading ? (
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
              <div className="mx-auto grid w-full max-w-7xl gap-4 px-4 py-4 sm:gap-5 sm:px-6 lg:grid-cols-[minmax(280px,360px)_1fr] lg:px-8 lg:py-6 xl:grid-cols-[380px_1fr]">
                <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
                  <section className="rounded-lg border border-border bg-card p-4 sm:p-5">
                    <div className="flex items-start gap-4">
                      <div className="flex size-14 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground sm:size-16">
                        <User className="size-7" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <h2 className="break-words text-2xl font-bold tracking-tight text-foreground">
                          {display(lead.name, "Chưa rõ tên ứng viên")}
                        </h2>
                        <div className="mt-2 flex flex-wrap gap-2 text-sm text-muted-foreground">
                          {lead.lead_score ? (
                            <span className="rounded-md border border-border bg-muted px-2 py-1 font-medium">
                              {lead.lead_score}
                            </span>
                          ) : null}
                          {lead.lead_stage ? (
                            <span className="rounded-md border border-border bg-muted px-2 py-1 font-medium">
                              {lead.lead_stage}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>

                    <div className="mt-5 grid gap-3">
                      {profileHighlights(lead).map((item) => {
                        const Icon = item.icon;
                        return (
                          <div
                            key={item.label}
                            className="flex min-w-0 items-start gap-3 rounded-lg border border-border/70 bg-background px-3 py-3"
                          >
                            <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                            <div className="min-w-0">
                              <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                                {item.label}
                              </div>
                              <div className="mt-0.5 break-words text-sm font-medium leading-relaxed text-foreground">
                                {display(item.value, item.fallback)}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    <div className="mt-5 flex flex-col gap-2 sm:flex-row lg:flex-col xl:flex-row">
                      {!isEditing ? (
                        <button
                          type="button"
                          onClick={handleEditClick}
                          className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
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
                            className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <Save className="size-4" />
                            {isSaving ? "Đang lưu..." : "Lưu hồ sơ"}
                          </button>
                          <button
                            type="button"
                            onClick={() => setIsEditing(false)}
                            disabled={isSaving}
                            className="inline-flex min-h-11 flex-1 items-center justify-center rounded-lg border border-border bg-background px-4 text-sm font-semibold text-foreground transition-colors hover:bg-muted focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            Hủy
                          </button>
                        </>
                      )}
                    </div>
                  </section>
                </aside>

                <div className="space-y-4 sm:space-y-5">
                  <section className="rounded-lg border border-border bg-card p-4 sm:p-5">
                    <h3 className="text-lg font-semibold text-foreground">
                      Thông tin tuyển dụng
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
                        {EDITABLE_FIELDS.map((field) => (
                          <label
                            key={field}
                            className={`block min-w-0 ${field === "notes" ? "sm:col-span-2" : ""}`}
                          >
                            <span className="text-[11px] font-semibold uppercase text-muted-foreground">
                              {editLabels[String(field)]}
                            </span>
                            {field === "notes" ? (
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
                        {isLoadingMemories
                          ? "Đang tải..."
                          : `${memories.length} mục`}
                      </span>
                    </div>
                    {isLoadingMemories ? (
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
