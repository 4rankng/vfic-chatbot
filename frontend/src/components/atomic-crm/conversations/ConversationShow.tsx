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
import { Bot, Check, Handshake, UserRound, type LucideIcon } from "lucide-react";
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

  useEffect(() => {
    setIsContextOpen(false);
  }, [record?.id]);

  const openContextPanel = () => {
    setIsContextOpen(true);
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
                {showWorkspacePanel ? (
                  <button
                    type="button"
                    className="person-name person-name-button"
                    ref={contextTriggerRef}
                    onClick={openContextPanel}
                    aria-expanded={isContextOpen}
                    aria-controls="conversation-context-panel"
                  >
                    {name}
                  </button>
                ) : (
                  <span className="person-name">{name}</span>
                )}
              </div>
            </div>
          </div>
          <div className="header-actions">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className={`mode-menu-trigger mode-menu-trigger--primary ${activeMode}`}
                  aria-label="Đổi chế độ trả lời"
                  title="Đổi chế độ trả lời"
                  disabled={activeMode === "closed"}
                >
                  <ActiveModeIcon className="icon" />
                  <span className="mode-menu-trigger-label">
                    {activeModeOption?.label ?? "Chế độ trả lời"}
                  </span>
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
