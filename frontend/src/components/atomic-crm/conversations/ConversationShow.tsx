import { useEffect, useMemo, useState } from "react";
import {
  useRecordContext,
  useGetList,
  ShowBase,
  useNotify,
  useRefresh,
} from "ra-core";
import { Link } from "react-router";
import type {
  Conversation,
  Lead,
  LeadChatOpsActionResult,
  LeadTag,
} from "../types";
import { getRealtimeSocket } from "@/lib/vfic/realtimeSocket";
import { getLeadStatusColor } from "./conversationDisplay";
import { LeadProfilePanel } from "../leads/LeadProfilePanel";
import { ChatThread } from "./ChatThread";
import {
  type ConversationMode,
  useConversationActions,
} from "./useConversationActions";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  BookOpen,
  Bot,
  BotMessageSquare,
  Briefcase,
  BusFront,
  CalendarDays,
  CheckCircle2,
  Check,
  CircleDollarSign,
  Copy,
  FileBadge,
  Handshake,
  Home,
  MapPin,
  NotepadText,
  Phone,
  Plus,
  Sparkles,
  UserRound,
  WandSparkles,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import {
  deriveSystemTags,
  dispatchLeadTagsUpdated,
  fetchLeadAssist,
  fetchLeadTags,
  getAiAssistInsights,
  getAutomationRecipes,
  getTagMeta,
  type ManualLeadTagInput,
  OPERATIONAL_TAGS,
  readRecentLeadTags,
  rememberRecentLeadTags,
  runLeadChatOpsAction,
  saveLeadTags,
} from "./chatOpsWorkspace";

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
  const [isContextOpen, setIsContextOpen] = useState(false);
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

  const notify = useNotify();
  const refresh = useRefresh();
  const [quickSaving, setQuickSaving] = useState<string | null>(null);

  useEffect(() => {
    setIsContextOpen(false);
  }, [record?.id]);

  const refetchWorkspaceLead = async () => {
    await refetchLead();
    window.dispatchEvent(
      new CustomEvent("vfic:lead-updated", {
        detail: { lead_id: lead?.id, zalo_id: record?.zalo_chat_id },
      }),
    );
  };

  const runChatOpsAction = async (
    action: string,
    savingKey: string,
    successMessage: string,
  ): Promise<LeadChatOpsActionResult | null> => {
    if (!lead) return null;
    setQuickSaving(savingKey);
    try {
      const result = await runLeadChatOpsAction(lead.id, action);
      notify(successMessage, { type: "success" });
      dispatchLeadTagsUpdated(lead.id);
      await refetchWorkspaceLead();
      refresh();
      return result;
    } catch (e) {
      notify((e as Error).message || "Không thể cập nhật ChatOps", {
        type: "error",
      });
      return null;
    } finally {
      setQuickSaving(null);
    }
  };

  const runPanelChatOpsAction = (action: string) => {
    if (action === "mark_contacting") {
      return runChatOpsAction(
        action,
        "contacting",
        "Đã chuyển sang đang liên hệ.",
      );
    }
    if (action === "schedule_followup") {
      return runChatOpsAction(
        action,
        "followup",
        "Đã đặt lịch follow-up ngày mai.",
      );
    }
    if (action === "mark_registered") {
      return runChatOpsAction(action, "registered", "Đã chuyển sang đăng ký.");
    }
    return runChatOpsAction(
      action,
      "not_interested",
      "Đã gắn nhãn không quan tâm.",
    );
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
              <DropdownMenuContent
                align="end"
                sideOffset={10}
                className="mode-menu-content"
              >
                <DropdownMenuLabel className="mode-menu-label">
                  Chế độ trả lời
                </DropdownMenuLabel>
                <DropdownMenuSeparator className="mode-menu-separator" />
                {MODE_OPTIONS.map((option) => {
                  const isActive = activeMode === option.mode;
                  return (
                    <DropdownMenuItem
                      key={option.mode}
                      onSelect={() => {
                        if (!isActive) setConversationMode(option.mode);
                      }}
                      className={`mode-menu-item ${option.mode} ${isActive ? "active" : ""}`}
                      aria-current={isActive ? "true" : undefined}
                    >
                      <span className="mode-menu-icon">
                        <option.Icon className="icon" aria-hidden="true" />
                      </span>
                      <span className="mode-menu-copy">
                        <span className="mode-menu-title">{option.label}</span>
                        <span className="mode-menu-hint">{option.hint}</span>
                      </span>
                      <span className="mode-menu-check" aria-hidden="true">
                        {isActive ? <Check className="icon" /> : null}
                      </span>
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>
            {showWorkspacePanel && (
              <button
                type="button"
                className={`profile-info-btn context-info-btn ${isContextOpen ? "active" : ""}`}
                onClick={() => setIsContextOpen(true)}
                aria-label="Mở ngữ cảnh hội thoại"
                title="Mở ngữ cảnh hội thoại"
              >
                <Sparkles className="icon" />
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
          key={record?.id ?? "empty"}
          conversationId={record?.id ?? ""}
          conversation={record}
          isBotModeOverride={isBotMode}
          canHumanReplyOverride={canHumanReply}
          onTakeoverOverride={handleTakeover}
          showComposerTakeoverNotice={false}
        />

        {showWorkspacePanel && isContextOpen && (
          <button
            type="button"
            className="context-overlay-scrim"
            aria-label="Đóng ngữ cảnh"
            onClick={() => setIsContextOpen(false)}
          />
        )}
        <LeadProfilePanel
          open={isProfileOpen}
          onOpenChange={setIsProfileOpen}
          lead={lead}
        />
      </section>
      {showWorkspacePanel && (
        <ConversationContextPanel
          lead={lead}
          conversation={record}
          activeMode={activeMode}
          saving={quickSaving}
          open={isContextOpen}
          onClose={() => setIsContextOpen(false)}
          onOpenProfile={() => setIsProfileOpen(true)}
          onRunChatOpsAction={runPanelChatOpsAction}
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

type ContextTab = "candidate" | "assist" | "agent";

type CandidateInfoItem = {
  key: string;
  label: string;
  value: string;
  complete: boolean;
  Icon: LucideIcon;
};

const hasMeaningfulValue = (value: unknown) =>
  display(value) !== "Chưa có dữ liệu";

const notesInclude = (notes: string | null | undefined, terms: string[]) => {
  const normalized = notes?.toLocaleLowerCase("vi-VN") ?? "";
  return terms.some((term) => normalized.includes(term));
};

const ConversationContextPanel = ({
  lead,
  conversation,
  activeMode,
  saving,
  open,
  onClose,
  onOpenProfile,
  onRunChatOpsAction,
}: {
  lead?: Lead;
  conversation?: Conversation;
  activeMode: ConversationMode;
  saving: string | null;
  open: boolean;
  onClose: () => void;
  onOpenProfile: () => void;
  onRunChatOpsAction: (
    action: string,
  ) => Promise<LeadChatOpsActionResult | null>;
}) => {
  const disabled = !lead || saving !== null;
  const notify = useNotify();
  const [activeTab, setActiveTab] = useState<ContextTab>("candidate");
  const [serverTags, setServerTags] = useState<LeadTag[]>([]);
  const [serverAssist, setServerAssist] = useState<
    LeadChatOpsActionResult["assist"] | null
  >(null);
  const [tagSaving, setTagSaving] = useState<string | null>(null);
  const [tagPickerOpen, setTagPickerOpen] = useState(false);
  const [customTagInput, setCustomTagInput] = useState("");
  const [recentTags, setRecentTags] = useState<ManualLeadTagInput[]>(() =>
    readRecentLeadTags(),
  );
  const candidateInfoItems = useMemo<CandidateInfoItem[]>(() => {
    const notes = lead?.notes;
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
        label: "Họ tên",
        value: display(lead?.name),
        complete: hasMeaningfulValue(lead?.name),
        Icon: UserRound,
      },
      {
        key: "phone",
        label: "Số điện thoại",
        value: display(lead?.phone),
        complete: hasMeaningfulValue(lead?.phone),
        Icon: Phone,
      },
      {
        key: "birth",
        label: "Ngày sinh / tuổi",
        value: display(dateOfBirth),
        complete: Boolean(dateOfBirth),
        Icon: CalendarDays,
      },
      {
        key: "citizen-id",
        label: "CCCD",
        value: hasCitizenId ? "Đã ghi trong ghi chú" : "Cần hỏi thêm",
        complete: hasCitizenId,
        Icon: FileBadge,
      },
      {
        key: "experience",
        label: "Kinh nghiệm",
        value: display(lead?.years_experience),
        complete: hasMeaningfulValue(lead?.years_experience),
        Icon: Briefcase,
      },
      {
        key: "expectation",
        label: "Mong muốn",
        value: display(lead?.desired_job),
        complete: hasMeaningfulValue(lead?.desired_job),
        Icon: Handshake,
      },
      {
        key: "salary",
        label: "Mức lương",
        value: display(lead?.expected_salary),
        complete: hasMeaningfulValue(lead?.expected_salary),
        Icon: CircleDollarSign,
      },
      {
        key: "housing",
        label: "Yêu cầu chỗ ở",
        value: hasHousing ? "Đã ghi trong ghi chú" : "Cần hỏi thêm",
        complete: hasHousing,
        Icon: Home,
      },
      {
        key: "pickup",
        label: "Xe đưa đón",
        value: hasPickup ? "Đã ghi trong ghi chú" : "Cần hỏi thêm",
        complete: hasPickup,
        Icon: BusFront,
      },
      {
        key: "area",
        label: "Khu vực",
        value: display(area),
        complete: Boolean(area),
        Icon: MapPin,
      },
      {
        key: "address",
        label: "Địa chỉ hiện tại",
        value: display(lead?.address),
        complete: hasMeaningfulValue(lead?.address),
        Icon: Home,
      },
      {
        key: "notes",
        label: "Ghi chú tuyển dụng",
        value: display(lead?.notes),
        complete: hasMeaningfulValue(lead?.notes),
        Icon: NotepadText,
      },
    ];
  }, [lead]);
  const completedCandidateInfoCount = candidateInfoItems.filter(
    (item) => item.complete,
  ).length;
  const fallbackTags = useMemo<LeadTag[]>(
    () =>
      deriveSystemTags(lead, conversation).map((key) => {
        const meta = getTagMeta(key);
        return { key, label: meta.label, tone: meta.tone, system: true };
      }),
    [lead, conversation],
  );
  const activeTags = serverTags.length > 0 ? serverTags : fallbackTags;
  const activeTagSet = useMemo(
    () => new Set(activeTags.map((tag) => tag.key)),
    [activeTags],
  );
  const manualTags = useMemo<ManualLeadTagInput[]>(
    () =>
      activeTags
        .filter((tag) => !tag.system)
        .map((tag) => ({ key: tag.key, label: tag.label, tone: tag.tone })),
    [activeTags],
  );
  const activeTagLabels = useMemo(
    () => new Set(activeTags.map((tag) => tag.label.trim().toLowerCase())),
    [activeTags],
  );
  const suggestedTags = useMemo<ManualLeadTagInput[]>(() => {
    const candidates: ManualLeadTagInput[] = [];
    if (!lead?.phone?.trim()) {
      candidates.push({
        key: "can_xin_sdt",
        label: "Cần xin SĐT",
        tone: "warn",
      });
    }
    if (!lead?.desired_job?.trim()) {
      candidates.push({
        key: "chua_ro_cong_viec",
        label: "Chưa rõ công việc",
        tone: "info",
      });
    }
    if (!lead?.region?.trim() && !lead?.living_area?.trim()) {
      candidates.push({
        key: "chua_ro_khu_vuc",
        label: "Chưa rõ khu vực",
        tone: "info",
      });
    }
    if (!lead?.next_action_at) {
      candidates.push({
        key: "can_hen_follow_up",
        label: "Cần hẹn follow-up",
        tone: "info",
      });
    }
    return candidates
      .filter((tag) => !activeTagLabels.has(tag.label.toLowerCase()))
      .slice(0, 2);
  }, [activeTagLabels, lead]);
  const availableRecentTags = useMemo(
    () =>
      recentTags
        .filter((tag) => !activeTagSet.has(tag.key))
        .filter((tag) => !activeTagLabels.has(tag.label.trim().toLowerCase()))
        .slice(0, 4),
    [activeTagLabels, activeTagSet, recentTags],
  );
  const fallbackAssist = useMemo(
    () => getAiAssistInsights(lead, conversation),
    [lead, conversation],
  );
  const fallbackRecipes = useMemo(
    () => getAutomationRecipes(lead, conversation),
    [lead, conversation],
  );
  const assist = {
    summary: serverAssist?.summary ?? fallbackAssist.summary,
    missing: serverAssist?.missing ?? fallbackAssist.missing,
    reply: serverAssist?.reply ?? fallbackAssist.reply,
    nextAction: serverAssist?.next_action ?? fallbackAssist.nextAction,
    modeLabel: serverAssist?.mode_label ?? fallbackAssist.modeLabel,
  };
  const recipes = serverAssist?.signals ?? fallbackRecipes;

  useEffect(() => {
    if (!lead?.id) {
      setServerTags([]);
      setServerAssist(null);
      setTagPickerOpen(false);
      setCustomTagInput("");
      return;
    }
    if (!open) return;
    setTagPickerOpen(false);
    setCustomTagInput("");
    let cancelled = false;
    (async () => {
      try {
        const [tags, assistPayload] = await Promise.all([
          fetchLeadTags(lead.id),
          fetchLeadAssist(lead.id),
        ]);
        if (cancelled) return;
        setServerTags(tags);
        setServerAssist(assistPayload);
      } catch {
        if (cancelled) return;
        setServerTags([]);
        setServerAssist(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [lead?.id, conversation?.id, open]);

  const saveManualTags = async (nextTags: ManualLeadTagInput[]) => {
    if (!lead) return;
    try {
      const tags = await saveLeadTags(lead.id, nextTags);
      setServerTags(tags);
      const nextRecent = tags
        .filter((tag) => !tag.system)
        .map((tag) => ({ key: tag.key, label: tag.label, tone: tag.tone }));
      rememberRecentLeadTags(nextRecent);
      setRecentTags(readRecentLeadTags());
      dispatchLeadTagsUpdated(lead.id);
      notify("Đã cập nhật thẻ ứng viên.", { type: "success" });
    } catch (e) {
      notify((e as Error).message || "Không thể cập nhật thẻ", {
        type: "error",
      });
      throw e;
    }
  };

  const handleToggleTag = async (tag: ManualLeadTagInput) => {
    if (!lead) return;
    const current = new Map(manualTags.map((item) => [item.key, item]));
    if (current.has(tag.key)) current.delete(tag.key);
    else {
      current.set(tag.key, {
        key: tag.key,
        label: tag.label.trim(),
        tone: tag.tone ?? "info",
      });
    }
    setTagSaving(tag.key);
    try {
      await saveManualTags(Array.from(current.values()));
    } finally {
      setTagSaving(null);
    }
  };

  const handleAddCustomTag = async () => {
    const label = customTagInput.trim();
    if (!label || !lead) return;
    if (activeTagLabels.has(label.toLowerCase())) {
      setCustomTagInput("");
      return;
    }
    setTagSaving(label);
    try {
      await saveManualTags([
        ...manualTags,
        { key: label, label, tone: "info" },
      ]);
      setCustomTagInput("");
    } finally {
      setTagSaving(null);
    }
  };

  const handleRunAction = async (action?: string | null) => {
    if (!action) return;
    const result = await onRunChatOpsAction(action);
    if (!result) return;
    setServerTags(result.tags);
    setServerAssist(result.assist);
  };

  const copySuggestedReply = async () => {
    try {
      await navigator.clipboard.writeText(assist.reply);
      notify("Đã sao chép gợi ý trả lời.", { type: "success" });
    } catch {
      notify("Không thể sao chép gợi ý.", { type: "warning" });
    }
  };

  return (
    <aside
      className={`panel right-panel ${open ? "context-open" : ""}`}
      aria-label="Bảng ngữ cảnh hội thoại"
      aria-hidden={!open}
    >
      <header className="profile-header">
        <div className="profile-title">
          <Sparkles className="icon" aria-hidden="true" />
          <span className="profile-title-copy">
            <span>Việc cần làm</span>
            <small>Ngữ cảnh hội thoại</small>
          </span>
        </div>
        <div className="context-header-actions">
          <button
            type="button"
            className="context-open-profile"
            onClick={onOpenProfile}
          >
            Mở hồ sơ
          </button>
          <button
            type="button"
            className="context-close"
            onClick={onClose}
            aria-label="Đóng ngữ cảnh"
          >
            ×
          </button>
        </div>
      </header>
      <div className="context-tabs" role="tablist" aria-label="Nhóm ngữ cảnh">
        <ContextTabButton
          active={activeTab === "candidate"}
          label="Tóm tắt"
          onClick={() => setActiveTab("candidate")}
        />
        <ContextTabButton
          active={activeTab === "assist"}
          label="AI gợi ý"
          onClick={() => setActiveTab("assist")}
        />
        <ContextTabButton
          active={activeTab === "agent"}
          label="Agent"
          onClick={() => setActiveTab("agent")}
        />
      </div>
      <div className="profile-scroll">
        <section className="context-overview">
          <div className="context-overview-copy">
            <span className="context-overview-kicker">Thẻ ứng viên</span>
            <h2>Phân loại hội thoại</h2>
            <p>
              Gắn thẻ để lọc lại ứng viên và nhắc đội tư vấn xử lý đúng việc.
            </p>
          </div>
          <div className="context-subject">
            <span className="context-subject-name">
              {display(lead?.name, "Ứng viên chưa liên kết")}
            </span>
            <span className="context-subject-role">
              {display(lead?.desired_job, "Chưa có vị trí mong muốn")}
            </span>
          </div>
          <div className="context-tags">
            {activeTags.map((tag) => (
              <span
                key={tag.key}
                className={`tag operational-tag ${tag.tone}`}
                title={tag.system ? "Thẻ hệ thống tự cập nhật" : "Thẻ thủ công"}
              >
                {tag.label}
              </span>
            ))}
            <button
              type="button"
              className="tag-add-button tag-add-button--labeled"
              disabled={!lead}
              aria-label="Thêm hoặc sửa thẻ ứng viên"
              aria-expanded={tagPickerOpen}
              onClick={() => setTagPickerOpen((open) => !open)}
              title="Thêm hoặc sửa thẻ"
            >
              <Plus className="icon" aria-hidden="true" />
              <span>Thẻ</span>
            </button>
          </div>
        </section>

        {activeTab === "candidate" && (
          <>
            {tagPickerOpen && (
              <section className="context-card">
                <div className="section-head">
                  <h3>Gắn thẻ</h3>
                </div>
                <div className="tag-custom-row">
                  <input
                    value={customTagInput}
                    onChange={(event) => setCustomTagInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        void handleAddCustomTag();
                      }
                    }}
                    placeholder="Nhập thẻ riêng..."
                    disabled={!lead || tagSaving !== null}
                    aria-label="Thẻ tùy chỉnh"
                  />
                  <button
                    type="button"
                    disabled={
                      !lead || !customTagInput.trim() || tagSaving !== null
                    }
                    onClick={() => {
                      void handleAddCustomTag();
                    }}
                  >
                    Thêm
                  </button>
                </div>
                {suggestedTags.length > 0 && (
                  <TagPickerGroup
                    title="Gợi ý"
                    tags={suggestedTags}
                    activeTagSet={activeTagSet}
                    tagSaving={tagSaving}
                    disabled={!lead}
                    onToggle={handleToggleTag}
                  />
                )}
                {availableRecentTags.length > 0 && (
                  <TagPickerGroup
                    title="Gần đây"
                    tags={availableRecentTags}
                    activeTagSet={activeTagSet}
                    tagSaving={tagSaving}
                    disabled={!lead}
                    onToggle={handleToggleTag}
                  />
                )}
                <div className="tag-picker-label">Có sẵn</div>
                <div className="tag-picker" aria-label="Gắn thẻ ứng viên">
                  {OPERATIONAL_TAGS.map((tag) => {
                    const selected = activeTagSet.has(tag.key);
                    const activeTag = activeTags.find(
                      (item) => item.key === tag.key,
                    );
                    const isSystemTag = Boolean(
                      tag.system || activeTag?.system,
                    );
                    return (
                      <button
                        key={tag.key}
                        type="button"
                        className={`tag-picker-chip ${tag.tone} ${
                          selected ? "active" : ""
                        }`}
                        disabled={!lead || isSystemTag || tagSaving === tag.key}
                        onClick={() => {
                          void handleToggleTag({
                            key: tag.key,
                            label: tag.label,
                            tone: tag.tone,
                          });
                        }}
                        title={
                          isSystemTag ? "Thẻ hệ thống tự cập nhật" : tag.label
                        }
                      >
                        {tagSaving === tag.key ? "Đang lưu..." : tag.label}
                      </button>
                    );
                  })}
                </div>
              </section>
            )}

            <section className="context-card">
              <div className="section-head">
                <h3>Thông tin cần dùng</h3>
                <span className="completion-pill">
                  {completedCandidateInfoCount}/{candidateInfoItems.length}
                </span>
              </div>
              <div className="candidate-info-grid">
                {candidateInfoItems.map((item) => (
                  <CandidateInfoRow key={item.key} item={item} />
                ))}
              </div>
            </section>
          </>
        )}

        {activeTab === "assist" && (
          <>
            <section className="context-card">
              <div className="section-head">
                <h3>Gợi ý nhanh</h3>
              </div>
              <div className="assist-stack">
                <div className="assist-block">
                  <span className="assist-label">Tóm tắt</span>
                  <p>{assist.summary}</p>
                </div>
                <div className="assist-block">
                  <span className="assist-label">Thiếu thông tin</span>
                  <p>
                    {assist.missing.length > 0
                      ? assist.missing.join(", ")
                      : "Đủ trường chính"}
                  </p>
                </div>
                <div className="assist-block suggested-reply">
                  <span className="assist-label">Gợi ý trả lời</span>
                  <p>{assist.reply}</p>
                  <button
                    type="button"
                    className="inline-tool-btn"
                    onClick={copySuggestedReply}
                  >
                    <Copy className="icon" aria-hidden="true" />
                    <span>Sao chép</span>
                  </button>
                </div>
                <div className="assist-block">
                  <span className="assist-label">Bước tiếp theo</span>
                  <p>{assist.nextAction}</p>
                </div>
              </div>
            </section>

            <section className="context-card">
              <div className="section-head">
                <h3>Tín hiệu</h3>
              </div>
              <div className="recipe-list">
                {recipes.map((recipe) => (
                  <div
                    key={recipe.key}
                    className={`recipe-row ${recipe.active ? "active" : ""}`}
                  >
                    <Workflow className="icon" aria-hidden="true" />
                    <span>
                      <span className="recipe-name">{recipe.name}</span>
                      <span className="recipe-status">{recipe.status}</span>
                    </span>
                    {recipe.action && (
                      <button
                        type="button"
                        className="inline-tool-btn recipe-action"
                        disabled={disabled}
                        onClick={() => {
                          void handleRunAction(recipe.action);
                        }}
                      >
                        <span>Áp dụng</span>
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </section>
          </>
        )}

        {activeTab === "agent" && (
          <section className="context-card">
            <div className="section-head">
              <h3>Sức khỏe agent</h3>
            </div>
            <div className="health-list">
              <ContextStatus
                Icon={WandSparkles}
                label="Chế độ"
                value={assist.modeLabel}
                healthy={activeMode !== "closed"}
              />
              <ContextStatus
                Icon={CheckCircle2}
                label="Thông tin ứng viên"
                value={
                  assist.missing.length === 0
                    ? "Đủ dữ liệu chính"
                    : `Thiếu ${assist.missing.length} trường`
                }
                healthy={assist.missing.length === 0}
              />
              <ContextStatus
                Icon={BookOpen}
                label="Training"
                value="Mở knowledge để kiểm tra nguồn"
                healthy
              />
            </div>
            <div className="context-link-list">
              <Link to="/knowledge_sources" className="context-link">
                <BookOpen className="icon" aria-hidden="true" />
                <span>Training knowledge</span>
              </Link>
              <Link to="/personas" className="context-link">
                <BotMessageSquare className="icon" aria-hidden="true" />
                <span>Manage agent</span>
              </Link>
              <Link to="/projects" className="context-link">
                <Briefcase className="icon" aria-hidden="true" />
                <span>Project catalog</span>
              </Link>
            </div>
          </section>
        )}
      </div>
    </aside>
  );
};

const ContextTabButton = ({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) => (
  <button
    type="button"
    role="tab"
    aria-selected={active}
    className={`context-tab ${active ? "active" : ""}`}
    onClick={onClick}
  >
    {label}
  </button>
);

const TagPickerGroup = ({
  title,
  tags,
  activeTagSet,
  tagSaving,
  disabled,
  onToggle,
}: {
  title: string;
  tags: ManualLeadTagInput[];
  activeTagSet: Set<string>;
  tagSaving: string | null;
  disabled: boolean;
  onToggle: (tag: ManualLeadTagInput) => Promise<void>;
}) => (
  <div className="tag-picker-group">
    <div className="tag-picker-label">{title}</div>
    <div className="tag-picker" aria-label={title}>
      {tags.map((tag) => {
        const selected = activeTagSet.has(tag.key);
        return (
          <button
            key={`${title}-${tag.key}`}
            type="button"
            className={`tag-picker-chip ${tag.tone ?? "info"} ${
              selected ? "active" : ""
            }`}
            disabled={disabled || tagSaving === tag.key}
            onClick={() => {
              void onToggle(tag);
            }}
          >
            {tagSaving === tag.key ? "Đang lưu..." : tag.label}
          </button>
        );
      })}
    </div>
  </div>
);

const CandidateInfoRow = ({ item }: { item: CandidateInfoItem }) => {
  const Icon = item.Icon;
  return (
    <div className={`candidate-info-row ${item.complete ? "filled" : ""}`}>
      <span className="candidate-info-icon">
        <Icon className="icon" aria-hidden="true" />
      </span>
      <span className="candidate-info-copy">
        <span className="candidate-info-label">{item.label}</span>
        <span className="candidate-info-value">{item.value}</span>
      </span>
      <span className="candidate-info-state" aria-hidden="true">
        {item.complete ? <Check className="icon" /> : null}
      </span>
    </div>
  );
};

const ContextStatus = ({
  Icon,
  label,
  value,
  healthy,
}: {
  Icon: LucideIcon;
  label: string;
  value: string;
  healthy: boolean;
}) => (
  <div className={`context-status ${healthy ? "healthy" : "warning"}`}>
    <span className="detail-icon">
      <Icon className="icon" aria-hidden="true" />
    </span>
    <span>
      <span className="detail-label">{label}</span>
      <span className="detail-value">{value}</span>
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
