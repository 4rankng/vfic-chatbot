import { useState } from "react";
import { useRecordContext, useGetList, ShowBase } from "ra-core";
import type { Conversation, Lead } from "../types";
import { getLeadStatusColor } from "./ConversationList";
import { LeadProfilePanel } from "../leads/LeadProfilePanel";
import { ChatThread } from "./ChatThread";
import { useConversationActions } from "./useConversationActions";

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
  const { isBotMode, handleTakeover } = useConversationActions(record);

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
          </div>
        </div>
        <div className="header-actions">
          {isBotMode && (
            <>
              <span
                className="chat-mode-chip"
                title="AI đang trả lời cuộc trò chuyện này"
              >
                <svg className="icon">
                  <use href="#i-bot" />
                </svg>
                <span>AI đang trả lời</span>
              </span>
              <button
                type="button"
                className="takeover-btn takeover-btn--header"
                onClick={handleTakeover}
              >
                Tiếp quản
              </button>
            </>
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
