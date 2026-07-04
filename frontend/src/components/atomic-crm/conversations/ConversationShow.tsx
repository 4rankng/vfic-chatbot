import { useEffect, useMemo, useState } from "react";
import {
  useRecordContext,
  useGetList,
  ShowBase,
  useNotify,
  useRefresh,
  useDataProvider,
} from "ra-core";
import { Link } from "react-router";
import type { Conversation, Lead } from "../types";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import { apiJson } from "../providers/rest/api";
import { getRealtimeSocket } from "@/lib/vfic/realtimeSocket";
import { getLeadStatusColor } from "./conversationDisplay";
import { LeadProfilePanel } from "../leads/LeadProfilePanel";
import { ChatThread } from "./ChatThread";
import {
  type ConversationMode,
  useConversationActions,
} from "./useConversationActions";
import { useRoleActions } from "../hooks/useRoleActions";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Confirm } from "@/components/admin/confirm";
import {
  Ban,
  BookOpen,
  Bot,
  Briefcase,
  Clock3,
  Handshake,
  Phone,
  Save,
  Sparkles,
  Trash2,
  UserRound,
  type LucideIcon,
} from "lucide-react";

type ReplyMode = Extract<ConversationMode, "human" | "semi_auto" | "bot">;

const MODE_OPTIONS: Array<{
  mode: ReplyMode;
  label: string;
  hint: string;
  title: string;
  Icon: LucideIcon;
}> = [
  {
    mode: "human",
    label: "Tư vấn viên",
    hint: "Người phụ trách",
    title: "Tư vấn viên - chỉ nhân sự trả lời ứng viên",
    Icon: UserRound,
  },
  {
    mode: "semi_auto",
    label: "Bán tự động",
    hint: "ChatBot hỗ trợ",
    title: "Bán tự động - ChatBot tiếp quản khi tư vấn viên không phản hồi",
    Icon: Handshake,
  },
  {
    mode: "bot",
    label: "Chatbot",
    hint: "ChatBot trả lời",
    title: "Chatbot - ChatBot xử lý cuộc trò chuyện",
    Icon: Bot,
  },
];

const MODE_STATUS: Record<ConversationMode, string> = {
  human: "Tư vấn viên · nhân sự trả lời",
  semi_auto: "Bán tự động · ChatBot hỗ trợ",
  bot: "Chatbot · đang trả lời",
  closed: "Closed",
};

/**
 * Inbox center pane: the conversation header (mobile list-toggle + person →
 * profile drawer) wrapped around a shared <ChatThread>. The thread itself
 * (messages, composer, takeover, markAsRead) lives in ChatThread so the lead
 * detail page can render the exact same thread without the inbox-shell coupling
 * that previously broke it. Must be rendered inside .inbox-bg-container — the
 * header chrome and the .center-panel grid are inbox-only.
 */
export const ConversationShowContent = ({
  onOpenList,
  showWorkspacePanel = false,
}: {
  onOpenList?: () => void;
  showWorkspacePanel?: boolean;
}) => {
  const record = useRecordContext<Conversation>();
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const leadListParams = useMemo(
    () => ({
      filter: { zalo_id: record?.zalo_chat_id },
      pagination: { page: 1, perPage: 1 },
    }),
    [record?.zalo_chat_id],
  );
  const leadListOptions = useMemo(
    () => ({ enabled: !!record?.zalo_chat_id }),
    [record?.zalo_chat_id],
  );

  const { data: leadData, refetch: refetchLead } = useGetList(
    "leads",
    leadListParams,
    leadListOptions,
  );
  const lead = leadData?.[0] as Lead | undefined;

  useEffect(() => {
    if (!lead?.id) return;
    const leadId = String(lead.id);
    const socket = getRealtimeSocket();
    const handleLeadUpdated = (payload: {
      id?: string | number;
      lead_id?: string | number;
      zalo_id?: string | null;
    }) => {
      const payloadLeadId = payload?.lead_id ?? payload?.id;
      const sameLead =
        payloadLeadId != null && String(payloadLeadId) === leadId;
      const sameZalo =
        !!payload?.zalo_id && payload.zalo_id === record?.zalo_chat_id;
      if (!sameLead && !sameZalo) return;
      void refetchLead();
    };

    socket.on("lead.updated", handleLeadUpdated);
    if (!socket.connected) {
      socket.connect();
    }
    socket.emit("join lead", { lead_id: lead.id });

    return () => {
      socket.off("lead.updated", handleLeadUpdated);
      socket.emit("leave lead", { lead_id: lead.id });
    };
  }, [lead?.id, record?.zalo_chat_id, refetchLead]);

  const name =
    lead?.name || `Ứng viên · ${(record?.zalo_chat_id || "").slice(-4)}`;
  const colors = getLeadStatusColor(lead);
  const {
    effectiveMode,
    isBotMode,
    canHumanReply,
    setConversationMode,
    handleTakeover,
  } = useConversationActions(record);
  const activeMode = effectiveMode ?? record?.mode ?? "bot";
  const activeModeOption = MODE_OPTIONS.find(
    (option) => option.mode === activeMode,
  );
  const ActiveModeIcon = activeModeOption?.Icon ?? Bot;

  const { isAdmin } = useRoleActions();
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const refresh = useRefresh();
  const [clearOpen, setClearOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [quickSaving, setQuickSaving] = useState<string | null>(null);
  const [threadVersion, setThreadVersion] = useState(0);

  const handleClearHistory = async () => {
    setClearing(true);
    try {
      await dataProvider.clearConversationHistory(record!.id);
      notify("Đã xóa lịch sử chat.", { type: "success" });
      setClearOpen(false);
      setThreadVersion((k) => k + 1);
      refresh();
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setClearing(false);
    }
  };

  const refetchWorkspaceLead = async () => {
    await refetchLead();
    window.dispatchEvent(
      new CustomEvent("vfic:lead-updated", {
        detail: { lead_id: lead?.id, zalo_id: record?.zalo_chat_id },
      }),
    );
  };

  const markNotInterested = async () => {
    if (!lead) return;
    setQuickSaving("not_interested");
    try {
      await dataProvider.update("leads", {
        id: lead.id,
        data: {
          lead_score: "not_interested",
          lead_stage: "SKIPPED",
          notes: lead.notes ?? "Ứng viên không quan tâm.",
        },
        previousData: lead,
      });
      notify("Đã gắn nhãn không quan tâm.", { type: "success" });
      await refetchWorkspaceLead();
      refresh();
    } catch (e) {
      notify((e as Error).message || "Không thể cập nhật ứng viên", {
        type: "error",
      });
    } finally {
      setQuickSaving(null);
    }
  };

  const markContacting = async () => {
    if (!lead) return;
    setQuickSaving("contacting");
    try {
      await dataProvider.update("leads", {
        id: lead.id,
        data: { lead_stage: "CONTACTING" },
        previousData: lead,
      });
      notify("Đã chuyển sang đang liên hệ.", { type: "success" });
      await refetchWorkspaceLead();
      refresh();
    } catch (e) {
      notify((e as Error).message || "Không thể cập nhật giai đoạn", {
        type: "error",
      });
    } finally {
      setQuickSaving(null);
    }
  };

  const scheduleTomorrowFollowup = async () => {
    if (!lead) return;
    setQuickSaving("followup");
    try {
      const dueAt = new Date();
      dueAt.setDate(dueAt.getDate() + 1);
      dueAt.setHours(9, 0, 0, 0);
      await apiJson(`/api/v1/leads/${lead.id}/follow-ups`, {
        method: "POST",
        body: {
          due_at: dueAt.toISOString(),
          note: "Theo dõi lại từ màn hình chat.",
        },
      });
      await dataProvider.update("leads", {
        id: lead.id,
        data: { next_action_at: dueAt.toISOString() },
        previousData: lead,
      });
      notify("Đã đặt lịch follow-up ngày mai.", { type: "success" });
      await refetchWorkspaceLead();
      refresh();
    } catch (e) {
      notify((e as Error).message || "Không thể đặt lịch follow-up", {
        type: "error",
      });
    } finally {
      setQuickSaving(null);
    }
  };

  return (
    <>
      <section className="panel center-panel" aria-label="Nội dung trò chuyện">
        <header className="chat-header">
          <button
            className="icon-btn mobile-toggle list-toggle"
            onClick={onOpenList}
            aria-label="Mở danh sách hội thoại"
          >
            <svg className="icon">
              <use href="#i-menu" />
            </svg>
          </button>
          <div
            className="header-person cursor-pointer hover:opacity-80 transition-opacity"
            onClick={() => setIsProfileOpen(true)}
          >
            <div
              className="header-avatar"
              style={{
                background: colors.bg,
                color: colors.ink,
              }}
            >
              <UserRound
                className="icon"
                style={{ width: "18px", height: "18px" }}
              />
            </div>
            <div className="person-copy">
              <div className="person-name-row">
                <span className="person-name">{name}</span>
              </div>
              <div className="person-meta">
                <span className={`mode-dot ${activeMode}`} />
                <span>{MODE_STATUS[activeMode]}</span>
              </div>
            </div>
          </div>
          <div className="header-actions">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className={`mode-menu-trigger ${activeMode}`}
                  aria-label="Chọn chế độ trả lời"
                  title="Chọn chế độ trả lời"
                  disabled={activeMode === "closed"}
                >
                  <ActiveModeIcon className="icon" />
                  <span>{activeModeOption?.label ?? "Closed"}</span>
                  <svg className="icon mode-menu-chevron">
                    <use href="#i-chevron" />
                  </svg>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuLabel>Chế độ trả lời</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {MODE_OPTIONS.map((option) => {
                  const isActive = activeMode === option.mode;
                  return (
                    <DropdownMenuItem
                      key={option.mode}
                      disabled={isActive}
                      onSelect={() => setConversationMode(option.mode)}
                      className="items-start gap-3"
                    >
                      <option.Icon className="mt-0.5 size-4 shrink-0" />
                      <span className="grid gap-0.5">
                        <span className="font-medium">{option.label}</span>
                        <span className="text-xs text-muted-foreground">
                          {option.hint}
                        </span>
                      </span>
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>
            <button
              type="button"
              className="profile-info-btn"
              onClick={() => setIsProfileOpen(true)}
              aria-label="Xem hồ sơ ứng viên"
              title="Xem hồ sơ ứng viên"
            >
              <svg className="icon">
                <use href="#i-panel" />
              </svg>
              <span>Hồ sơ</span>
            </button>
            {isAdmin && (
              <button
                type="button"
                className="profile-info-btn"
                title="Xóa chat"
                aria-label="Xóa chat"
                onClick={() => setClearOpen(true)}
              >
                <Trash2 className="icon" />
                <span>Xóa chat</span>
              </button>
            )}
            {activeMode === "closed" && (
              <span className="chat-mode-chip" title="Hội thoại đã đóng">
                <Bot className="icon" />
                <span>Đã đóng</span>
              </span>
            )}
          </div>
        </header>

        <ChatThread
          key={`${record?.id ?? "empty"}:${threadVersion}`}
          conversationId={record?.id ?? ""}
          conversation={record}
          isBotModeOverride={isBotMode}
          canHumanReplyOverride={canHumanReply}
          onTakeoverOverride={handleTakeover}
          showComposerTakeoverNotice={false}
        />

        <LeadProfilePanel
          open={isProfileOpen}
          onOpenChange={setIsProfileOpen}
          lead={lead}
        />

        <Confirm
          isOpen={clearOpen}
          title="Xóa toàn bộ lịch sử chat?"
          content="Toàn bộ tin nhắn và nhật ký chatbot của hội thoại này sẽ bị xóa vĩnh viễn. Thông tin ứng viên và hội thoại được giữ lại. Hành động không thể hoàn tác."
          confirm="Xóa vĩnh viễn"
          confirmColor="warning"
          loading={clearing}
          onClose={() => setClearOpen(false)}
          onConfirm={handleClearHistory}
        />
      </section>
      {showWorkspacePanel && (
        <ConversationContextPanel
          lead={lead}
          activeMode={activeMode}
          saving={quickSaving}
          onOpenProfile={() => setIsProfileOpen(true)}
          onMarkContacting={markContacting}
          onMarkNotInterested={markNotInterested}
          onScheduleFollowup={scheduleTomorrowFollowup}
        />
      )}
    </>
  );
};

const display = (value: unknown, fallback = "Chưa có dữ liệu") => {
  if (value === undefined || value === null) return fallback;
  const text = String(value).trim();
  return text || fallback;
};

const ConversationContextPanel = ({
  lead,
  activeMode,
  saving,
  onOpenProfile,
  onMarkContacting,
  onMarkNotInterested,
  onScheduleFollowup,
}: {
  lead?: Lead;
  activeMode: ConversationMode;
  saving: string | null;
  onOpenProfile: () => void;
  onMarkContacting: () => void;
  onMarkNotInterested: () => void;
  onScheduleFollowup: () => void;
}) => {
  const disabled = !lead || saving !== null;
  const followupLabel = lead?.next_action_at
    ? new Date(lead.next_action_at).toLocaleDateString("vi-VN")
    : "Chưa đặt lịch";

  return (
    <aside className="panel right-panel" aria-label="Bảng ngữ cảnh hội thoại">
      <header className="profile-header">
        <div className="profile-title">
          <UserRound className="icon" aria-hidden="true" />
          <span>Ngữ cảnh</span>
        </div>
        <button
          type="button"
          className="context-open-profile"
          onClick={onOpenProfile}
        >
          Mở hồ sơ
        </button>
      </header>
      <div className="profile-scroll">
        <section className="context-card context-hero">
          <div className="context-avatar">
            <UserRound className="icon" aria-hidden="true" />
          </div>
          <div className="context-hero-copy">
            <h2>{display(lead?.name, "Ứng viên chưa liên kết")}</h2>
            <p>{display(lead?.desired_job, "Chưa có vị trí mong muốn")}</p>
          </div>
          <div className="context-tags">
            <span className="tag">{MODE_STATUS[activeMode]}</span>
            {lead?.phone ? <span className="tag good">Có SĐT</span> : null}
            {lead?.lead_score === "not_interested" ? (
              <span className="tag">Không quan tâm</span>
            ) : null}
          </div>
        </section>

        <section className="context-card">
          <div className="section-head">
            <h3>Ứng viên</h3>
          </div>
          <div className="detail-list compact">
            <ContextDetail
              Icon={Phone}
              label="Số điện thoại"
              value={lead?.phone}
            />
            <ContextDetail
              Icon={Briefcase}
              label="Khu vực"
              value={lead?.region ?? lead?.living_area}
            />
            <ContextDetail
              Icon={Clock3}
              label="Follow-up"
              value={followupLabel}
            />
          </div>
        </section>

        <section className="context-card">
          <div className="section-head">
            <h3>Thao tác nhanh</h3>
          </div>
          <div className="context-action-grid">
            <button
              type="button"
              className="context-action"
              disabled={disabled}
              onClick={onMarkContacting}
            >
              <Save className="icon" aria-hidden="true" />
              <span>
                {saving === "contacting" ? "Đang lưu..." : "Đang liên hệ"}
              </span>
            </button>
            <button
              type="button"
              className="context-action"
              disabled={disabled}
              onClick={onScheduleFollowup}
            >
              <Clock3 className="icon" aria-hidden="true" />
              <span>{saving === "followup" ? "Đang đặt..." : "Follow-up"}</span>
            </button>
            <button
              type="button"
              className="context-action danger"
              disabled={disabled}
              onClick={onMarkNotInterested}
            >
              <Ban className="icon" aria-hidden="true" />
              <span>
                {saving === "not_interested"
                  ? "Đang lưu..."
                  : "Không quan tâm"}
              </span>
            </button>
          </div>
        </section>

        <section className="context-card">
          <div className="section-head">
            <h3>Agent</h3>
          </div>
          <div className="context-link-list">
            <Link to="/knowledge_sources" className="context-link">
              <BookOpen className="icon" aria-hidden="true" />
              <span>Training knowledge</span>
            </Link>
            <Link to="/personas" className="context-link">
              <Sparkles className="icon" aria-hidden="true" />
              <span>Manage agent</span>
            </Link>
            <Link to="/projects" className="context-link">
              <Briefcase className="icon" aria-hidden="true" />
              <span>Project catalog</span>
            </Link>
          </div>
        </section>
      </div>
    </aside>
  );
};

const ContextDetail = ({
  Icon,
  label,
  value,
}: {
  Icon: LucideIcon;
  label: string;
  value: unknown;
}) => (
  <div className="detail-row">
    <span className="detail-icon">
      <Icon className="icon" aria-hidden="true" />
    </span>
    <span>
      <span className="detail-label">{label}</span>
      <span className={`detail-value ${value ? "" : "missing"}`}>
        {display(value)}
      </span>
    </span>
  </div>
);

export const ConversationShow = () => {
  return (
    <ShowBase>
      <ConversationShowContent />
    </ShowBase>
  );
};
