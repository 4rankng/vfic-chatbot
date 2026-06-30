import { useMemo, useState } from "react";
import {
  useRecordContext,
  useGetList,
  ShowBase,
  usePermissions,
  useNotify,
  useRefresh,
  useDataProvider,
} from "ra-core";
import type { Conversation, Lead } from "../types";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
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
import { Confirm } from "@/components/admin/confirm";
import { Trash2 } from "lucide-react";

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
    label: "Tư vấn viên",
    hint: "Người phụ trách",
    title: "Tư vấn viên - chỉ nhân sự trả lời ứng viên",
    icon: "i-user",
  },
  {
    mode: "semi_auto",
    label: "Bán tự động",
    hint: "ChatBot hỗ trợ",
    title: "Bán tự động - ChatBot tiếp quản khi tư vấn viên không phản hồi",
    icon: "i-sparkles",
  },
  {
    mode: "bot",
    label: "Chatbot",
    hint: "ChatBot trả lời",
    title: "Chatbot - ChatBot xử lý cuộc trò chuyện",
    icon: "i-bot",
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
}: {
  onOpenList?: () => void;
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

  const { data: leadData } = useGetList(
    "leads",
    leadListParams,
    leadListOptions,
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

  const { permissions } = usePermissions();
  const isAdmin = permissions === "admin";
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const refresh = useRefresh();
  const [clearOpen, setClearOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [threadKey, setThreadKey] = useState(0);

  const handleClearHistory = async () => {
    setClearing(true);
    try {
      await dataProvider.clearConversationHistory(record!.id);
      notify("Đã xóa lịch sử chat.", { type: "success" });
      setClearOpen(false);
      setThreadKey((k) => k + 1);
      refresh();
    } catch (e) {
      notify((e as Error).message, { type: "error" });
    } finally {
      setClearing(false);
    }
  };

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
              <svg className="icon">
                <use href="#i-bot" />
              </svg>
              <span>Đã đóng</span>
            </span>
          )}
        </div>
      </header>

      <ChatThread
        key={threadKey}
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
  );
};

export const ConversationShow = () => {
  return (
    <ShowBase>
      <ConversationShowContent />
    </ShowBase>
  );
};
