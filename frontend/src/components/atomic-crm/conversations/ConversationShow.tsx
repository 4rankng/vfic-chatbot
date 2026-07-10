import { useEffect, useMemo, useRef, useState } from "react";
import { useRecordContext, useGetList, ShowBase } from "ra-core";
import type { Conversation, Lead } from "../types";
import { getRealtimeSocket } from "@/lib/vfic/realtimeSocket";
import { getLeadStatusColor } from "./conversationDisplay";
import { ChatThread } from "./ChatThread";
import {
  type ConversationMode,
  useConversationActions,
} from "./useConversationActions";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Bot,
  BusFront,
  CalendarDays,
  Check,
  CircleDollarSign,
  FileText,
  Handshake,
  Home,
  MapPin,
  MoreHorizontal,
  NotepadText,
  Phone,
  UserRound,
  FileBadge,
  type LucideIcon,
} from "lucide-react";
import { ConversationContextPanel } from "./ConversationContextPanel";
import { useIsMobile } from "@/hooks/use-mobile";

type ReplyMode = Extract<ConversationMode, "human" | "semi_auto" | "bot">;

const MODE_OPTIONS: Array<{
  mode: ReplyMode;
  label: string;
  title: string;
  Icon: LucideIcon;
}> = [
  {
    mode: "human",
    label: "Tư vấn viên",
    title: "Tư vấn viên - chỉ nhân sự trả lời ứng viên",
    Icon: UserRound,
  },
  {
    mode: "semi_auto",
    label: "Bán tự động",
    title: "Bán tự động - ChatBot tiếp quản khi tư vấn viên không phản hồi",
    Icon: Handshake,
  },
  {
    mode: "bot",
    label: "Chatbot",
    title: "Chatbot - ChatBot xử lý cuộc trò chuyện",
    Icon: Bot,
  },
];

type CandidateSignal = {
  key: string;
  label: string;
  value: string;
  Icon: LucideIcon;
};

const displaySignalValue = (value: unknown) => {
  if (value === undefined || value === null) return "";
  return String(value).trim();
};

const formatGender = (gender: string | null | undefined) => {
  const normalized = displaySignalValue(gender).toLocaleLowerCase("vi-VN");
  if (!normalized || normalized === "unknown") return "";
  if (normalized === "male" || normalized === "nam") return "Nam";
  if (normalized === "female" || normalized === "nữ" || normalized === "nu") {
    return "Nữ";
  }
  return displaySignalValue(gender);
};

const notesInclude = (notes: string | null | undefined, terms: string[]) => {
  const normalized = notes?.toLocaleLowerCase("vi-VN") ?? "";
  return terms.some((term) => normalized.includes(term));
};

const getCandidateSignals = (lead?: Lead): CandidateSignal[] => {
  if (!lead) return [];

  const signals: CandidateSignal[] = [];
  const addSignal = (
    key: string,
    label: string,
    value: unknown,
    Icon: LucideIcon,
  ) => {
    const text = displaySignalValue(value);
    if (!text) return;
    signals.push({ key, label, value: text, Icon });
  };

  addSignal("phone", "Số điện thoại", lead.phone, Phone);
  addSignal(
    "residence",
    "Nơi cư trú",
    [lead.region, lead.living_area, lead.address].filter(Boolean).join(" · "),
    MapPin,
  );
  addSignal("gender", "Giới tính", formatGender(lead.gender), UserRound);
  addSignal(
    "birth",
    "Ngày sinh",
    lead.birth_year
      ? String(lead.birth_year)
      : lead.age
        ? `${lead.age} tuổi`
        : "",
    CalendarDays,
  );
  addSignal("experience", "Kinh nghiệm", lead.years_experience, FileBadge);
  addSignal("job", "Công việc mong muốn", lead.desired_job, Handshake);
  addSignal(
    "salary",
    "Mức lương mong muốn",
    lead.expected_salary,
    CircleDollarSign,
  );

  if (
    notesInclude(lead.notes, [
      "chỗ ở",
      "cho o",
      "nhà trọ",
      "nha tro",
      "ký túc",
      "ky tuc",
      "ktx",
    ])
  ) {
    signals.push({
      key: "housing",
      label: "Chỗ ở",
      value: "Đã ghi trong ghi chú",
      Icon: Home,
    });
  }

  if (
    notesInclude(lead.notes, [
      "đưa đón",
      "dua don",
      "xe đưa",
      "xe dua",
      "xe đón",
      "xe don",
      "bus",
      "tuyến xe",
      "tuyen xe",
    ])
  ) {
    signals.push({
      key: "pickup",
      label: "Xe đưa đón",
      value: "Đã ghi trong ghi chú",
      Icon: BusFront,
    });
  }

  addSignal("notes", "Ghi chú", lead.notes, NotepadText);

  return signals;
};

/**
 * Inbox center pane: the conversation header (mobile list-toggle + candidate
 * quick facts) wrapped around a shared <ChatThread>. The thread itself
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
  const isMobile = useIsMobile();
  const contextTriggerRef = useRef<HTMLButtonElement>(null);
  const [isContextOpen, setIsContextOpen] = useState(false);
  const [activeSignalKey, setActiveSignalKey] = useState<string | null>(null);
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
  const candidateSignals = useMemo(() => getCandidateSignals(lead), [lead]);
  const activeSignal =
    candidateSignals.find((signal) => signal.key === activeSignalKey) ?? null;
  const {
    effectiveMode,
    isBotMode,
    canHumanReply,
    setConversationMode,
    handleTakeover,
    handleRelease,
  } = useConversationActions(record);
  const activeMode = effectiveMode ?? record?.mode ?? "bot";
  const activeModeOption = MODE_OPTIONS.find(
    (option) => option.mode === activeMode,
  );
  const ActiveModeIcon = activeModeOption?.Icon ?? Bot;

  useEffect(() => {
    setIsContextOpen(false);
    setActiveSignalKey(null);
  }, [record?.id]);

  useEffect(() => {
    if (
      activeSignalKey &&
      !candidateSignals.some((signal) => signal.key === activeSignalKey)
    ) {
      setActiveSignalKey(null);
    }
  }, [activeSignalKey, candidateSignals]);

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
          <div className="header-person">
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
              {candidateSignals.length > 0 && (
                <div
                  className="candidate-signal-strip"
                  aria-label="Thông tin ứng viên đã thu thập"
                  role="list"
                >
                  {candidateSignals.map(({ key, label, value, Icon }) => {
                    const isActive = activeSignalKey === key;
                    return (
                      <button
                        key={key}
                        type="button"
                        className={`candidate-signal-icon ${isActive ? "active" : ""}`}
                        title={`${label}: ${value}`}
                        aria-label={`${label}: ${value}`}
                        aria-expanded={isActive}
                        aria-controls="candidate-signal-value"
                        role="listitem"
                        onClick={(event) => {
                          event.stopPropagation();
                          setActiveSignalKey(isActive ? null : key);
                        }}
                      >
                        <Icon className="icon" aria-hidden="true" />
                      </button>
                    );
                  })}
                  {activeSignal ? (
                    <div
                      className="candidate-signal-popover"
                      id="candidate-signal-value"
                      role="status"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <span className="candidate-signal-label">
                        {activeSignal.label}
                      </span>
                      <span className="candidate-signal-value">
                        {activeSignal.value}
                      </span>
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          </div>
          <div className="header-actions">
            {activeMode === "bot" ? (
              <button
                type="button"
                className="takeover-btn takeover-btn--header"
                onClick={handleTakeover}
              >
                Tiếp nhận
              </button>
            ) : canHumanReply ? (
              <button
                type="button"
                className="takeover-btn takeover-btn--header"
                onClick={handleRelease}
              >
                Trả lại Chatbot
              </button>
            ) : null}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className={`mode-menu-trigger ${activeMode}`}
                  aria-label="Tùy chọn chế độ trả lời"
                  title="Tùy chọn chế độ trả lời"
                  disabled={activeMode === "closed"}
                >
                  <ActiveModeIcon className="icon" />
                  <span className="sr-only">Tùy chọn</span>
                  <MoreHorizontal className="icon" aria-hidden="true" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                sideOffset={10}
                className="mode-menu-content"
              >
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
                      <span className="mode-menu-title">{option.label}</span>
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
                ref={contextTriggerRef}
                className={`profile-info-btn context-info-btn ${isContextOpen ? "active" : ""}`}
                onClick={() => setIsContextOpen(true)}
                aria-label="Mở ngữ cảnh hội thoại"
                title="Mở ngữ cảnh hội thoại"
              >
                <FileText className="icon" />
              </button>
            )}
            {activeMode === "closed" && (
              <span className="chat-mode-chip" title="Hội thoại đã đóng; không có thao tác tiếp nhận">
                <Bot className="icon" />
                <span>Hội thoại đã đóng</span>
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

        {showWorkspacePanel && isContextOpen && !isMobile && (
          <button
            type="button"
            className="context-overlay-scrim"
            aria-label="Đóng ngữ cảnh"
            onClick={() => setIsContextOpen(false)}
          />
        )}
      </section>
      {showWorkspacePanel && (
        <ConversationContextPanel
          lead={lead}
          open={isContextOpen}
          onClose={() => setIsContextOpen(false)}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            contextTriggerRef.current?.focus();
          }}
        />
      )}
    </>
  );
};

export const ConversationShow = () => {
  return (
    <ShowBase>
      <ConversationShowContent />
    </ShowBase>
  );
};
