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
import { conversationChannelLabel, type Conversation } from "../../types";
import { deleteConversation } from "../application/conversation-operations";
import { resolveConversationDisplayChannel } from "../domain/conversation-channel-display";
import { channelIcon } from "../channel-icons";
import { Confirm } from "@/components/admin/confirm";
import { ChatThread } from "./ChatThread";
import { useConversationActions } from "./use-conversation-actions";
import { ButtonUtility } from "@/components/base/buttons/button-utility";
import { Dropdown } from "@/components/base/dropdown/dropdown";
import { MoreHorizontal, Trash2 } from "lucide-react";
import { ConversationHeader } from "./ConversationHeader";
import { ConversationReplyMode } from "./ConversationReplyMode";
import { useIsMobile, useIsWideDesktop } from "@/hooks/use-mobile";
import { ConversationContextAdapter } from "../conversation-capability";
import { useConversationCapabilitySlots } from "../useConversationCapabilitySlots";

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
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const {
    effectiveMode,
    isBotMode,
    needsClaim,
    canHumanReply,
    setConversationMode,
    handleTakeover,
    isChangingMode,
  } = useConversationActions(record);
  const activeMode = effectiveMode ?? record?.mode ?? "bot";
  // OA accounts share one provider id, so the channel glyph identifies the account the
  // channel_identity points at (TingTing OA vs the Viet Phap OA).
  const displayChannel = resolveConversationDisplayChannel(
    record?.channel_identity,
  );
  const channelGlyph = channelIcon(displayChannel);
  const channelLabel = conversationChannelLabel(displayChannel);

  useEffect(() => {
    setIsContextOpen(isWideDesktop || shouldOpenCandidatePanel);
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
            <ConversationHeader
              identity={context}
              onBack={onOpenList}
              onOpenCandidate={
                showWorkspacePanel && context.renderPanel
                  ? openContextPanel
                  : undefined
              }
              candidateOpen={isWideDesktop || isContextOpen}
              candidateTriggerRef={contextNameTriggerRef}
              actions={
                permissions === "admin" && record ? (
                  <Dropdown.Root>
                    <ButtonUtility
                      ref={conversationActionsTriggerRef}
                      size="sm"
                      color="tertiary"
                      className="uu-scope conversation-header-actions-button"
                      aria-label="Thao tác hội thoại"
                      icon={<MoreHorizontal aria-hidden="true" />}
                    />
                    <Dropdown.Popover
                      placement="bottom end"
                      offset={8}
                      className="uu-scope conversation-actions-menu"
                    >
                      <Dropdown.Menu>
                        <Dropdown.Item
                          id="delete-conversation"
                          className="conversation-actions-item conversation-actions-item-danger"
                          icon={Trash2}
                          label="Xoá hội thoại"
                          onPress={() => setDeleteOpen(true)}
                        />
                      </Dropdown.Menu>
                    </Dropdown.Popover>
                  </Dropdown.Root>
                ) : null
              }
            />

            <ChatThread
              key={record?.id ?? "empty"}
              conversationId={record?.id ?? ""}
              conversation={record}
              candidateAvatarUrl={context.avatarUrl}
              isBotModeOverride={isBotMode}
              needsClaimOverride={needsClaim}
              canHumanReplyOverride={canHumanReply}
              onTakeoverOverride={handleTakeover}
              isChangingModeOverride={isChangingMode}
              composerToolbar={
                <>
                  {activeMode !== "closed" ? (
                    <div className="composer-channel-mode">
                      {channelGlyph ? (
                        <img
                          src={channelGlyph}
                          alt={channelLabel}
                          title={channelLabel}
                          className="composer-channel-icon"
                        />
                      ) : null}
                      <ConversationReplyMode
                        mode={activeMode}
                        needsClaim={needsClaim}
                        isChangingMode={isChangingMode}
                        onChange={setConversationMode}
                      />
                    </div>
                  ) : null}
                  {CapabilityActions ? (
                    <CapabilityActions conversation={record} />
                  ) : null}
                </>
              }
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
                onCloseAutoFocus: (event: Event) => {
                  event.preventDefault();
                  focusContextTrigger();
                },
              })
            : null}
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
