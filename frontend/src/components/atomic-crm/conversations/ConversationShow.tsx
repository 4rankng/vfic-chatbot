import { useState } from "react";
import { useRecordContext, useGetList, ShowBase } from "ra-core";
import type { Conversation, Lead } from "../types";
import { getLeadStatusColor } from "./ConversationList";
import { LeadProfilePanel } from "../leads/LeadProfilePanel";
import { ChatThread } from "./ChatThread";
import {
  type ConversationMode,
  useConversationActions,
} from "./useConversationActions";

type ReplyMode = Extract<ConversationMode, "human" | "semi_auto" | "bot">;

const MODE_OPTIONS: Array<{
  mode: ReplyMode;
  label: string;
  hint: string;
  title: string;
  icon: string;
}> = [
  {
    mode: "human",
    label: "Manual",
    hint: "Human only",
    title: "Manual mode - only human can chat to candidate",
    icon: "i-user",
  },
  {
    mode: "semi_auto",
    label: "Semi auto",
    hint: "5 min fallback",
    title: "Semi auto - chatbot takes over if human is inactive for 5 minutes",
    icon: "i-sparkles",
  },
  {
    mode: "bot",
    label: "Auto",
    hint: "Bot handles",
    title: "Auto - chatbot handles the conversation",
    icon: "i-bot",
  },
];

const MODE_STATUS: Record<ConversationMode, string> = {
  human: "Manual mode: only recruiter replies are enabled",
  semi_auto: "Semi auto: bot answers after 5 minutes of recruiter inactivity",
  bot: "Auto mode: chatbot is handling replies",
  closed: "Conversation closed",
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
}: {
  onOpenList?: () => void;
}) => {
  const record = useRecordContext<Conversation>();
  const [isProfileOpen, setIsProfileOpen] = useState(false);

  const { data: leadData } = useGetList(
    "leads",
    {
      filter: { zalo_id: record?.zalo_chat_id },
      pagination: { page: 1, perPage: 1 },
    },
    { enabled: !!record?.zalo_chat_id },
  );
  const lead = leadData?.[0] as Lead | undefined;

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

  return (
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
              backgroundImage: "none",
            }}
          >
            <svg className="icon" style={{ width: "18px", height: "18px" }}>
              <use href="#i-user" />
            </svg>
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
          <div
            className="mode-control"
            role="radiogroup"
            aria-label="Chế độ trả lời hội thoại"
          >
            {MODE_OPTIONS.map((option) => {
              const isActive = activeMode === option.mode;
              return (
                <button
                  key={option.mode}
                  type="button"
                  className={`mode-segment ${option.mode} ${
                    isActive ? "active" : ""
                  }`}
                  role="radio"
                  aria-checked={isActive}
                  title={option.title}
                  disabled={activeMode === "closed" || isActive}
                  onClick={() => setConversationMode(option.mode)}
                >
                  <svg className="icon">
                    <use href={`#${option.icon}`} />
                  </svg>
                  <span className="mode-segment-copy">
                    <span className="mode-segment-label">{option.label}</span>
                    <span className="mode-segment-hint">{option.hint}</span>
                  </span>
                </button>
              );
            })}
          </div>
          {activeMode === "closed" && (
            <span className="chat-mode-chip" title="Hội thoại đã đóng">
              <svg className="icon">
                <use href="#i-bot" />
              </svg>
              <span>Đã đóng</span>
            </span>
          )}
          <button
            className="icon-btn small mobile-toggle profile-toggle"
            onClick={() => setIsProfileOpen(true)}
            aria-label="Mở hồ sơ ứng viên"
          >
            <svg className="icon">
              <use href="#i-panel" />
            </svg>
          </button>
        </div>
      </header>

      <ChatThread
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
    </section>
  );
};

export const ConversationShow = () => {
  return (
    <ShowBase>
      <ConversationShowContent />
    </ShowBase>
  );
};
