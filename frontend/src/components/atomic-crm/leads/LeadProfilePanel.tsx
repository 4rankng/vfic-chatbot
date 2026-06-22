import { useEffect, useState } from "react";
import { useRecordContext, useDataProvider, useNotify } from "ra-core";
import type { Conversation, Lead } from "../types";
import type { CrmDataProvider } from "../providers/supabase/dataProvider";

export const LeadProfilePanel = () => {
  const conversation = useRecordContext<Conversation>();
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
    if (!zaloChatId) {
      setLead(null);
      setNotFound(true);
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
  }, [dataProvider, zaloChatId]);

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
    } catch (e) {
      notify("Lỗi khi cập nhật hồ sơ", { type: "error" });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <aside className="panel right-panel" aria-label="Hồ sơ ứng viên">
      <div className="profile-header">
        <div className="profile-title">
          <svg className="icon">
            <use href="#i-user" />
          </svg>
          <span>Hồ sơ ứng viên</span>
        </div>
        <div className="profile-header-actions">
          <button className="icon-btn small ghost" aria-label="Tùy chọn">
            <svg className="icon">
              <use href="#i-more" />
            </svg>
          </button>
        </div>
      </div>
      <div className="profile-scroll">
        {isLoading ? (
          <div className="empty-state">Đang tải hồ sơ...</div>
        ) : notFound || !lead ? (
          <div className="empty-state">Chưa liên kết hồ sơ ứng viên</div>
        ) : (
          <>
            <section className="profile-section">
              <div className="section-head">
                <h3>Thông tin tuyển dụng</h3>
                {!isEditing ? (
                  <button type="button" onClick={handleEditClick}>
                    Chỉnh sửa
                  </button>
                ) : (
                  <div className="flex gap-3">
                    <button
                      type="button"
                      style={{ color: "var(--ink-muted)" }}
                      onClick={() => setIsEditing(false)}
                      disabled={isSaving}
                    >
                      Hủy
                    </button>
                    <button
                      type="button"
                      onClick={handleSave}
                      disabled={isSaving}
                    >
                      {isSaving ? "Đang lưu..." : "Lưu"}
                    </button>
                  </div>
                )}
              </div>
              <div className="detail-list">
                <div className="detail-row">
                  <span className="detail-icon">
                    <svg className="icon">
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
                        className="w-full bg-transparent border-b border-border focus:border-primary outline-none transition-colors detail-value pb-1 mt-1"
                        value={editData.phone || ""}
                        onChange={(e) =>
                          setEditData({ ...editData, phone: e.target.value })
                        }
                        placeholder="Nhập số điện thoại"
                        disabled={isSaving}
                      />
                    )}
                  </div>
                </div>
                <div className="detail-row">
                  <span className="detail-icon">
                    <svg className="icon">
                      <use href="#i-briefcase" />
                    </svg>
                  </span>
                  <div className="flex-1">
                    <div className="detail-label">Công việc mong muốn</div>
                    {!isEditing ? (
                      <div
                        className={`detail-value ${!lead.desired_job ? "missing cursor-pointer hover:text-[var(--brand)] transition-colors" : ""}`}
                        onClick={() => !lead.desired_job && handleEditClick()}
                      >
                        {lead.desired_job || "Thêm công việc"}
                      </div>
                    ) : (
                      <input
                        type="text"
                        className="w-full bg-transparent border-b border-border focus:border-primary outline-none transition-colors detail-value pb-1 mt-1"
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
                    <svg className="icon">
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
                        className="w-full bg-transparent border-b border-border focus:border-primary outline-none transition-colors detail-value pb-1 mt-1"
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
    </aside>
  );
};
