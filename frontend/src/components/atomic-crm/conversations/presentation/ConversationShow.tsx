import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import {
  useDataProvider,
  useNotify,
  usePermissions,
  useRecordContext,
  useRefresh,
  ShowBase,
} from "ra-core";
import type { Conversation } from "../../types";
import { deleteConversation } from "../application/conversation-operations";
import { Confirm } from "@/components/admin/confirm";
import { LeadAvatar } from "../LeadAvatar";
import { ChatThread } from "./ChatThread";
import {
  type ConversationMode,
  useConversationActions,
} from "./use-conversation-actions";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Bot,
  Check,
  ChevronDown,
  Handshake,
  History,
  MoreHorizontal,
  PanelRight,
  Phone,
  Trash2,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { useIsMobile, useIsWideDesktop } from "@/hooks/use-mobile";
import {
  ConversationContextAdapter,
  useConversationCapabilitySlots,
} from "../conversation-capability";
import { DecisionTracePanel } from "../../automation/DecisionTracePanel";

type ReplyMode = Extract<ConversationMode, "human" | "semi_auto" | "bot">;

const MODE_OPTIONS: Array<{
  mode: ReplyMode;
  label: string;
  title: string;
  description: string;
  Icon: LucideIcon;
}> = [
  {
    mode: "human",
    label: "Tư vấn viên",
    title: "Tư vấn viên - chỉ nhân sự trả lời người trò chuyện",
    description: "Nhân viên trả lời trực tiếp",
    Icon: UserRound,
  },
  {
    mode: "semi_auto",
    label: "Bán tự động",
    title: "Bán tự động - ChatBot tiếp quản khi tư vấn viên không phản hồi",
    description: "Chatbot hỗ trợ khi cần",
    Icon: Handshake,
  },
  {
    mode: "bot",
    label: "Chatbot",
    title: "Chatbot - ChatBot xử lý cuộc trò chuyện",
    description: "Chatbot tự động xử lý",
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
  onDeleted,
  showWorkspacePanel = false,
}: {
  onOpenList?: () => void;
  /** Called after a successful hard-delete so the parent can drop the now-stale
   * selection and URL param — otherwise react-admin's `refresh()` re-fetches
   * the list but `selectedId` still points at the deleted row, leaving the
   * detail pane pinned to a conversation that no longer exists. */
  onDeleted?: () => void;
  showWorkspacePanel?: boolean;
}) => {
  const record = useRecordContext<Conversation>();
  const isMobile = useIsMobile();
  const isWideDesktop = useIsWideDesktop();
  const dataProvider = useDataProvider();
  const notify = useNotify();
  const refresh = useRefresh();
  const { permissions } = usePermissions();
  const slots = useConversationCapabilitySlots();
  const CapabilityActions = slots.actions;
  const contextNameTriggerRef = useRef<HTMLButtonElement>(null);
  const lastContextTriggerRef = useRef<HTMLButtonElement>(null);
  const conversationActionsTriggerRef = useRef<HTMLButtonElement>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const shouldOpenCandidatePanel = searchParams.get("panel") === "candidate";
  const [isContextOpen, setIsContextOpen] = useState(false);
  const [isDecisionTraceOpen, setIsDecisionTraceOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const {
    effectiveMode,
    isBotMode,
    needsClaim,
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
    setIsContextOpen(isWideDesktop || shouldOpenCandidatePanel);
    setIsDecisionTraceOpen(false);
  }, [isWideDesktop, record?.id, shouldOpenCandidatePanel]);

  const openContextPanel = (trigger?: HTMLButtonElement) => {
    lastContextTriggerRef.current = trigger ?? contextNameTriggerRef.current;
    setIsContextOpen(true);
  };

  const focusContextTrigger = () => {
    (lastContextTriggerRef.current ?? contextNameTriggerRef.current)?.focus();
  };

  const closeContextPanel = () => {
    setIsContextOpen(false);
    if (!isMobile) focusContextTrigger();
    if (searchParams.get("panel") !== "candidate") return;
    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete("panel");
    setSearchParams(nextParams, { replace: true });
  };

  const handleDeleteConversation = async () => {
    if (!record || isDeleting) return;
    setIsDeleting(true);
    try {
      await deleteConversation(
        {
          deleteConversation: () =>
            dataProvider.delete("conversations", {
              id: record.id,
              previousData: record,
            }),
        },
        String(record.id),
      );
      notify("Đã xóa vĩnh viễn hội thoại.", { type: "success" });
      setDeleteOpen(false);
      // Hand control back to the parent BEFORE refreshing. The parent clears
      // `selectedId` and the `?id=` URL param, which unmounts this panel;
      // react-admin's list cache is then refreshed so the deleted row is gone
      // when the list pane re-renders. Calling `refresh()` first leaves the
      // detail pane pinned to the deleted record until the next list click.
      onDeleted?.();
      refresh();
    } catch (error) {
      notify((error as Error).message, { type: "error" });
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <ConversationContextAdapter conversation={record}>
      {(context) => (
        <>
          <section
            className="panel center-panel"
            aria-label="Nội dung trò chuyện"
          >
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
                {showWorkspacePanel && context.renderPanel ? (
                  <button
                    type="button"
                    className="header-avatar-button"
                    onClick={(event) => openContextPanel(event.currentTarget)}
                    aria-label={`Xem thông tin ứng viên của ${context.displayName}`}
                    aria-expanded={isWideDesktop || isContextOpen}
                    aria-controls="conversation-context-panel"
                  >
                    <LeadAvatar
                      src={context.avatarUrl}
                      bg={context.avatarBackground}
                      ink={context.avatarForeground}
                      iconSize={18}
                      className="header-avatar"
                      alt={context.avatarAlt}
                    />
                  </button>
                ) : (
                  <LeadAvatar
                    src={context.avatarUrl}
                    bg={context.avatarBackground}
                    ink={context.avatarForeground}
                    iconSize={18}
                    className="header-avatar"
                    alt={context.avatarAlt}
                  />
                )}
                <div className="person-copy">
                  <div className="person-name-row">
                    {showWorkspacePanel && context.renderPanel ? (
                      <button
                        type="button"
                        className="person-name person-name-button"
                        ref={contextNameTriggerRef}
                        onClick={(event) =>
                          openContextPanel(event.currentTarget)
                        }
                        aria-expanded={isWideDesktop || isContextOpen}
                        aria-controls="conversation-context-panel"
                      >
                        {context.displayName}
                      </button>
                    ) : (
                      <span className="person-name">{context.displayName}</span>
                    )}
                  </div>
                  {context.contactSubtitle && (
                    <div className="person-subtitle">
                      {context.contactSubtitle.secondaryName && (
                        <span className="person-subtitle-name">
                          {context.contactSubtitle.secondaryName}
                        </span>
                      )}
                      {context.contactSubtitle.secondaryName &&
                      context.contactSubtitle.phone ? (
                        <span
                          className="person-subtitle-sep"
                          aria-hidden="true"
                        >
                          ·
                        </span>
                      ) : null}
                      {context.contactSubtitle.phone && (
                        <span className="person-subtitle-phone">
                          <Phone
                            className="person-subtitle-icon"
                            aria-hidden="true"
                          />
                          <span>{context.contactSubtitle.phone}</span>
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
              <div className="header-actions">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button
                      type="button"
                      className={`mode-menu-trigger mode-menu-trigger--primary tt-btn tt-btn-sm ${activeMode}`}
                      aria-label="Đổi chế độ trả lời"
                      title="Đổi chế độ trả lời"
                      disabled={activeMode === "closed" || needsClaim}
                    >
                      <span className="mode-menu-trigger-icon">
                        <ActiveModeIcon className="icon" aria-hidden="true" />
                      </span>
                      <span className="mode-menu-trigger-label">
                        {activeModeOption?.label ?? "Chế độ trả lời"}
                      </span>
                      <ChevronDown
                        className="mode-menu-trigger-chevron"
                        aria-hidden="true"
                      />
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
                          <span className="mode-menu-copy">
                            <span className="mode-menu-title">
                              {option.label}
                            </span>
                            <span className="mode-menu-description">
                              {option.description}
                            </span>
                          </span>
                          <span className="mode-menu-check" aria-hidden="true">
                            {isActive ? <Check className="icon" /> : null}
                          </span>
                        </DropdownMenuItem>
                      );
                    })}
                  </DropdownMenuContent>
                </DropdownMenu>
                {(permissions === "admin" && record) ||
                (!isWideDesktop && context.renderPanel) ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        ref={conversationActionsTriggerRef}
                        type="button"
                        className="icon-btn ghost"
                        aria-label="Thao tác hội thoại"
                        title="Thao tác hội thoại"
                      >
                        <MoreHorizontal className="icon" aria-hidden="true" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                      align="end"
                      sideOffset={10}
                      className="conversation-actions-menu"
                    >
                      {permissions === "admin" && record ? (
                        <DropdownMenuItem
                          onSelect={() => setIsDecisionTraceOpen(true)}
                        >
                          <History className="size-4" aria-hidden="true" />
                          Agent Thinking
                        </DropdownMenuItem>
                      ) : null}
                      {!isWideDesktop && context.renderPanel ? (
                        <DropdownMenuItem onSelect={() => openContextPanel()}>
                          <PanelRight className="size-4" aria-hidden="true" />
                          {context.panelLabel}
                        </DropdownMenuItem>
                      ) : null}
                      {permissions === "admin" && record ? (
                        <>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            variant="destructive"
                            onSelect={(event) => {
                              event.preventDefault();
                              setDeleteOpen(true);
                            }}
                          >
                            <Trash2 className="size-4" aria-hidden="true" />
                            Xoá hội thoại
                          </DropdownMenuItem>
                        </>
                      ) : null}
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : null}
                {CapabilityActions ? (
                  <CapabilityActions conversation={record} />
                ) : null}
                {activeMode === "closed" && (
                  <span
                    className="chat-mode-chip"
                    title="Hội thoại đã đóng; không có thao tác tiếp nhận"
                  >
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
              candidateAvatarUrl={context.avatarUrl}
              isBotModeOverride={isBotMode}
              needsClaimOverride={needsClaim}
              canHumanReplyOverride={canHumanReply}
              onTakeoverOverride={handleTakeover}
            />

            {showWorkspacePanel &&
              context.renderPanel &&
              isContextOpen &&
              !isMobile &&
              !isWideDesktop && (
                <button
                  type="button"
                  className="context-overlay-scrim"
                  aria-label="Đóng ngữ cảnh"
                  onClick={closeContextPanel}
                />
              )}
          </section>
          {showWorkspacePanel && context.renderPanel
            ? context.renderPanel({
                open: isWideDesktop || isContextOpen,
                persistent: isWideDesktop,
                onClose: closeContextPanel,
                onCloseAutoFocus: (event) => {
                  event.preventDefault();
                  focusContextTrigger();
                },
              })
            : null}
          {permissions === "admin" && record ? (
            <DecisionTracePanel
              key={record.id}
              conversationId={String(record.id)}
              open={isDecisionTraceOpen}
              onOpenChange={setIsDecisionTraceOpen}
              showTrigger={false}
              returnFocusRef={conversationActionsTriggerRef}
            />
          ) : null}
          <Confirm
            isOpen={deleteOpen}
            loading={isDeleting}
            title="Xóa hội thoại?"
            content="Toàn bộ tin nhắn và lượt xử lý chatbot của hội thoại này sẽ bị xóa. Hành động này không thể hoàn tác."
            confirm="Xóa vĩnh viễn"
            confirmColor="warning"
            onClose={() => setDeleteOpen(false)}
            onConfirm={() => void handleDeleteConversation()}
          />
        </>
      )}
    </ConversationContextAdapter>
  );
};

export const ConversationShow = () => {
  return (
    <ShowBase>
      <ConversationShowContent />
    </ShowBase>
  );
};
