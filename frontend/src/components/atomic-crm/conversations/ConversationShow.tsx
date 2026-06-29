import { useState } from "react";
import { useRecordContext, useGetList, ShowBase } from "ra-core";
import type { Conversation, Lead } from "../types";
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
  human: "Manual · recruiter replies",
  semi_auto: "Semi auto · bot fallback",
  bot: "Auto · bot replies",
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
  const activeModeOption = MODE_OPTIONS.find(
    (option) => option.mode === activeMode,
  );

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
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={`mode-menu-trigger ${activeMode}`}
                aria-label="Chọn chế độ trả lời"
                title="Chọn chế độ trả lời"
                disabled={activeMode === "closed"}
              >
                <svg className="icon">
                  <use href={`#${activeModeOption?.icon ?? "i-bot"}`} />
                </svg>
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
                    <svg className="mt-0.5 size-4 shrink-0">
                      <use href={`#${option.icon}`} />
                    </svg>
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
