import { memo, useEffect, useRef, useState } from "react";
import { useDataProvider, useNotify, useRecordContext } from "ra-core";
import { apiJson } from "../providers/rest/api";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import type { Conversation, Lead } from "../types";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

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
  { label: "Khu vực", value: [lead.region, lead.living_area].filter(Boolean).join(" · ") },
  { label: "Công ty gần nhất", value: lead.latest_company },
  { label: "Kinh nghiệm", value: lead.years_experience },
  { label: "Ghi chú", value: lead.notes },
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
      <DialogContent className="max-h-[min(760px,90vh)] max-w-2xl overflow-y-auto border-border bg-card p-6 text-card-foreground">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg font-bold text-foreground">
            <svg className="icon size-5" style={{ width: 18, height: 18 }}>
              <use href="#i-user" />
            </svg>
            Hồ sơ ứng viên
          </DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <div className="rounded-lg border border-border p-4 text-sm text-muted-foreground">
            Đang tải hồ sơ...
          </div>
        ) : notFound || !lead ? (
          <div className="rounded-lg border border-border p-4 text-sm text-muted-foreground">
            Chưa liên kết hồ sơ ứng viên
          </div>
        ) : (
          <div className="space-y-4">
            <section className="rounded-lg border border-border bg-muted/20 p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="truncate text-xl font-semibold text-foreground">
                    {display(lead.name, "Chưa rõ tên ứng viên")}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted-foreground">
                    <span>{display(lead.phone, "Chưa có số điện thoại")}</span>
                    {lead.lead_score ? <span>{lead.lead_score}</span> : null}
                    {lead.lead_stage ? <span>{lead.lead_stage}</span> : null}
                  </div>
                </div>
                {!isEditing ? (
                  <button
                    type="button"
                    onClick={handleEditClick}
                    className="shrink-0 text-sm font-medium text-primary hover:underline"
                  >
                    Chỉnh sửa
                  </button>
                ) : (
                  <div className="flex shrink-0 gap-3 text-sm font-medium">
                    <button
                      type="button"
                      style={{ color: "var(--ink-muted)" }}
                      onClick={() => setIsEditing(false)}
                      disabled={isSaving}
                      className="hover:underline"
                    >
                      Hủy
                    </button>
                    <button
                      type="button"
                      onClick={handleSave}
                      disabled={isSaving}
                      className="text-primary hover:underline"
                    >
                      {isSaving ? "Đang lưu..." : "Lưu"}
                    </button>
                  </div>
                )}
              </div>
            </section>

            <section className="rounded-lg border border-border p-4">
              <h3 className="text-sm font-semibold text-foreground">
                Thông tin tuyển dụng
              </h3>
              {!isEditing ? (
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {profileRows(lead).map((row) => (
                    <div key={row.label} className="min-w-0">
                      <div className="text-[11px] font-semibold uppercase text-muted-foreground">
                        {row.label}
                      </div>
                      <div
                        className={`mt-1 break-words text-sm ${row.value ? "text-foreground" : "text-muted-foreground"}`}
                      >
                        {display(row.value)}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {EDITABLE_FIELDS.map((field) => (
                    <label key={field} className="block min-w-0">
                      <span className="text-[11px] font-semibold uppercase text-muted-foreground">
                        {editLabels[String(field)]}
                      </span>
                      <input
                        type="text"
                        className="mt-1 w-full border-b border-border bg-transparent pb-1 text-sm text-foreground outline-none transition-colors focus:border-primary"
                        value={(editData[field] as string | null) ?? ""}
                        onChange={(e) =>
                          setEditData({
                            ...editData,
                            [field]: e.target.value,
                          })
                        }
                        disabled={isSaving}
                      />
                    </label>
                  ))}
                </div>
              )}
            </section>

            {lead.qualification_reasons?.length ? (
              <section className="rounded-lg border border-border p-4">
                <h3 className="text-sm font-semibold text-foreground">
                  Lý do đánh giá
                </h3>
                <ul className="mt-2 space-y-2 text-sm text-foreground">
                  {lead.qualification_reasons.map((reason) => (
                    <li key={reason} className="flex gap-2">
                      <span className="mt-1 size-1.5 shrink-0 rounded-full bg-primary" />
                      <span>{reason}</span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            <section className="rounded-lg border border-border p-4">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-foreground">
                  Ghi nhớ từ hội thoại
                </h3>
                <span className="text-xs text-muted-foreground">
                  {isLoadingMemories ? "Đang tải..." : `${memories.length} mục`}
                </span>
              </div>
              {isLoadingMemories ? (
                <div className="mt-3 text-sm text-muted-foreground">
                  Đang tải ghi nhớ...
                </div>
              ) : memories.length ? (
                <ul className="mt-3 space-y-2">
                  {memories.map((memory) => (
                    <li
                      key={memory.id}
                      className="rounded-md bg-muted/30 px-3 py-2 text-sm leading-relaxed text-foreground"
                    >
                      {memory.content}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="mt-3 text-sm text-muted-foreground">
                  Chưa có ghi nhớ nào cho ứng viên này.
                </div>
              )}
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};

export const LeadProfilePanel = memo(LeadProfilePanelImpl);
LeadProfilePanel.displayName = "LeadProfilePanel";
