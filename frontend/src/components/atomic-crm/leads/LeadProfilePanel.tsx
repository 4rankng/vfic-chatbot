import { memo, useEffect, useRef, useState } from "react";
import { useRecordContext, useDataProvider, useNotify } from "ra-core";
import type { Conversation, Lead } from "../types";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
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

// Memoized so the heavy dialog body (edit form, three input rows, save flow)
// does NOT re-render on every ConversationShow message-state change while the
// dialog is closed. All hooks run unconditionally; the early return below the
// hook block skips the expensive JSX tree when `open` is false.
const LeadProfilePanelImpl = ({
  open,
  onOpenChange,
  lead: leadProp,
}: LeadProfilePanelProps) => {
  const conversation = useRecordContext<Conversation>();
  // Mirror into a ref (not a dep) so a parent background refetch doesn't
  // re-trigger the open effect and discard an in-progress edit.
  const leadPropRef = useRef(leadProp);
  leadPropRef.current = leadProp;
  const dataProvider = useDataProvider<CrmDataProvider>();
  const [lead, setLead] = useState<Lead | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const notify = useNotify();

  const [isEditing, setIsEditing] = useState(false);
  const [editData, setEditData] = useState<Partial<Lead>>({});
  const [isSaving, setIsSaving] = useState(false);

  const zaloChatId = conversation?.zalo_chat_id;

  useEffect(() => {
    if (!zaloChatId || !open) {
      if (!zaloChatId) {
        setLead(null);
        setNotFound(true);
      }
      return;
    }
    // Reuse the parent's already-loaded lead instead of a duplicate getList;
    // fall back to fetching only if it isn't loaded yet (first-open race).
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

  // Skip the heavy dialog body entirely while closed — ConversationShowContent
  // re-renders on every message/keystroke, and without this early return the
  // full edit-form tree would be evaluated even though Radix Dialog unmounts
  // the portalled content. The Dialog wrapper still renders so Radix manages
  // the open/close transition; its body is the part we short-circuit.
  if (!open) return null;

  const handleEditClick = () => {
    setEditData({
      phone: lead?.phone || "",
      desired_job: lead?.desired_job || "",
      expected_salary: lead?.expected_salary || "",
    });
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
      <DialogContent className="max-w-md p-6 bg-card text-card-foreground border-border">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg font-bold text-foreground">
            <svg
              className="icon size-5"
              style={{ width: "18px", height: "18px" }}
            >
              <use href="#i-user" />
            </svg>
            Hồ sơ ứng viên
          </DialogTitle>
        </DialogHeader>
        <div className="inbox-bg-container !p-0 !h-auto !w-auto bg-transparent">
          <div className="profile-scroll" style={{ overflowY: "visible" }}>
            {isLoading ? (
              <div className="empty-state p-4 text-center">
                Đang tải hồ sơ...
              </div>
            ) : notFound || !lead ? (
              <div className="empty-state p-4 text-center">
                Chưa liên kết hồ sơ ứng viên
              </div>
            ) : (
              <>
                <section className="profile-section !mt-2">
                  <div className="section-head">
                    <h3 className="text-foreground">Thông tin tuyển dụng</h3>
                    {!isEditing ? (
                      <button
                        type="button"
                        onClick={handleEditClick}
                        className="cursor-pointer text-primary hover:underline"
                      >
                        Chỉnh sửa
                      </button>
                    ) : (
                      <div className="flex gap-3">
                        <button
                          type="button"
                          style={{ color: "var(--ink-muted)" }}
                          onClick={() => setIsEditing(false)}
                          disabled={isSaving}
                          className="cursor-pointer hover:underline"
                        >
                          Hủy
                        </button>
                        <button
                          type="button"
                          onClick={handleSave}
                          disabled={isSaving}
                          className="cursor-pointer text-primary hover:underline"
                        >
                          {isSaving ? "Đang lưu..." : "Lưu"}
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="detail-list">
                    <div className="detail-row">
                      <span className="detail-icon">
                        <svg
                          className="icon"
                          style={{ width: "18px", height: "18px" }}
                        >
                          <use href="#i-phone" />
                        </svg>
                      </span>
                      <div className="flex-1">
                        <div className="detail-label">Số điện thoại</div>
                        {!isEditing ? (
                          <div
                            className={`detail-value ${!lead.phone ? "missing cursor-pointer hover:text-[var(--brand)] transition-colors" : ""}`}
                            onClick={() => !lead.phone && handleEditClick()}
                          >
                            {lead.phone || "Thêm số điện thoại"}
                          </div>
                        ) : (
                          <input
                            type="text"
                            className="w-full bg-transparent border-b border-border focus:border-primary outline-none transition-colors detail-value pb-1 mt-1 text-foreground"
                            value={editData.phone || ""}
                            onChange={(e) =>
                              setEditData({
                                ...editData,
                                phone: e.target.value,
                              })
                            }
                            placeholder="Nhập số điện thoại"
                            disabled={isSaving}
                          />
                        )}
                      </div>
                    </div>
                    <div className="detail-row">
                      <span className="detail-icon">
                        <svg
                          className="icon"
                          style={{ width: "18px", height: "18px" }}
                        >
                          <use href="#i-briefcase" />
                        </svg>
                      </span>
                      <div className="flex-1">
                        <div className="detail-label">Công việc mong muốn</div>
                        {!isEditing ? (
                          <div
                            className={`detail-value ${!lead.desired_job ? "missing cursor-pointer hover:text-[var(--brand)] transition-colors" : ""}`}
                            onClick={() =>
                              !lead.desired_job && handleEditClick()
                            }
                          >
                            {lead.desired_job || "Thêm công việc"}
                          </div>
                        ) : (
                          <input
                            type="text"
                            className="w-full bg-transparent border-b border-border focus:border-primary outline-none transition-colors detail-value pb-1 mt-1 text-foreground"
                            value={editData.desired_job || ""}
                            onChange={(e) =>
                              setEditData({
                                ...editData,
                                desired_job: e.target.value,
                              })
                            }
                            placeholder="Nhập công việc"
                            disabled={isSaving}
                          />
                        )}
                      </div>
                    </div>
                    <div className="detail-row">
                      <span className="detail-icon">
                        <svg
                          className="icon"
                          style={{ width: "18px", height: "18px" }}
                        >
                          <use href="#i-coins" />
                        </svg>
                      </span>
                      <div className="flex-1">
                        <div className="detail-label">Lương mong muốn</div>
                        {!isEditing ? (
                          <div
                            className={`detail-value ${!lead.expected_salary ? "missing cursor-pointer hover:text-[var(--brand)] transition-colors" : ""}`}
                            onClick={() =>
                              !lead.expected_salary && handleEditClick()
                            }
                          >
                            {lead.expected_salary || "Thêm mức lương"}
                          </div>
                        ) : (
                          <input
                            type="text"
                            className="w-full bg-transparent border-b border-border focus:border-primary outline-none transition-colors detail-value pb-1 mt-1 text-foreground"
                            value={editData.expected_salary || ""}
                            onChange={(e) =>
                              setEditData({
                                ...editData,
                                expected_salary: e.target.value,
                              })
                            }
                            placeholder="Nhập mức lương"
                            disabled={isSaving}
                          />
                        )}
                      </div>
                    </div>
                  </div>
                </section>
              </>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export const LeadProfilePanel = memo(LeadProfilePanelImpl);
LeadProfilePanel.displayName = "LeadProfilePanel";
