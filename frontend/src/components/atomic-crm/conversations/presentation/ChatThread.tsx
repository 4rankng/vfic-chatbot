import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { VList, type VListHandle } from "virtua";
import { useGetIdentity, useNotify, useTranslate } from "ra-core";
import type { Conversation } from "../../types";
import {
  isHumanReplyFailure,
  markConversationAsRead,
  retryConversationReply,
  sendConversationReply,
} from "../application/conversation-operations";
import { isUnseenWorthyArrival } from "../domain/conversation-thread";
import { groupConversationMessages } from "../domain/conversation-thread-rows";
import { replyFailureMessageKey } from "../domain/reply-failure-messages";
import { resolveConversationDisplayChannel } from "../domain/conversation-channel-display";
import { useConversationActions } from "./use-conversation-actions";
import { useConversationRealtime } from "./use-conversation-realtime";
import { useConversationOperations } from "./use-conversation-operations";
import {
  useConversationMessages,
  useConversationFlags,
} from "./conversation-message-state";
import { ChatMessageRow } from "./ChatMessageRow";
import { LoadingState } from "../../misc/LoadingState";
import { Button } from "@/components/base/buttons/button";
import { Bot } from "lucide-react";
import { useIsMobile } from "@/hooks/use-mobile";

// ChatThread is the reusable message thread + composer. It owns the realtime
// subscription, the virtualised scroller (with all the snap / load-more arming
// logic), the reply composer and the bot→human takeover affordance. It renders a
// FRAGMENT (scroll shell + <footer/>) so the host shell lays out the scroller
// (1fr) and composer (auto) — the inbox center-panel grid does this. Styling
// comes from the .inbox-bg-container scope in inbox.css.
//
// What a message *is* — its grouping run and its bubble variant — belongs to
// the siblings: `domain/conversation-thread-rows` decides the row per stored
// message and `presentation/ChatMessageRow` renders one memoized bubble per
// row. What is left here is thread state: scroll position, history load-more,
// the composer, and the conversation writes routed through
// `useConversationOperations`.

const COMPOSER_TEXTAREA_MAX_HEIGHT = 120;
const DEFAULT_COMPOSER_RESERVE_PX = 104;
const COMPOSER_RESERVE_GAP_PX = 16;
// Distance from the bottom (px) within which auto-scroll is allowed.
const CHAT_AT_BOTTOM_THRESHOLD_PX = 96;
// Distance from the top (px) within which we trigger history load-more.
const HISTORY_LOAD_TOP_THRESHOLD_PX = 100;

export interface ChatThreadProps {
  conversationId: string;
  /** Conversation record — enables bot→human takeover and unread clearing.
   * Omitted on surfaces that only display the thread (none today, but the
   * thread degrades gracefully: no takeover, no markAsRead). */
  conversation?: Conversation;
  /** Candidate avatar URL (from the loaded lead). When present, user message
   * rows render the image; absent/null keeps the UserRound icon. Passed from
   * the parent surface so the thread never issues its own lead fetch. */
  candidateAvatarUrl?: string | null;
  isBotModeOverride?: boolean;
  needsClaimOverride?: boolean;
  canHumanReplyOverride?: boolean;
  onTakeoverOverride?: () => void | Promise<void>;
  isChangingModeOverride?: boolean;
  /** Host-owned reply mode and capability controls, measured with the footer. */
  composerToolbar?: ReactNode;
  showComposerTakeoverNotice?: boolean;
}

export const ChatThread = ({
  conversationId,
  conversation,
  candidateAvatarUrl,
  isBotModeOverride,
  needsClaimOverride,
  canHumanReplyOverride,
  onTakeoverOverride,
  isChangingModeOverride,
  composerToolbar,
  showComposerTakeoverNotice = true,
}: ChatThreadProps) => {
  // Message state lives in the normalized store (persists across conversation
  // switches). The hook drives data INTO the store; we read arrays out here.
  const messages = useConversationMessages(conversationId);
  const { isLoading, isLoadingMore, hasMore, initialError, historyError } =
    useConversationFlags(conversationId);
  const {
    loadMore,
    insertOptimistic,
    markOptimisticFailed,
    retryInitial,
    retryHistory,
  } = useConversationRealtime(conversationId);
  const operations = useConversationOperations();
  const { identity } = useGetIdentity();
  const notify = useNotify();
  const translate = useTranslate();
  const isMobile = useIsMobile();
  const composerHintId = useId();
  const [reply, setReply] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [takeoverFocusRequest, setTakeoverFocusRequest] = useState<{
    conversationId: string;
    settled: boolean;
  } | null>(null);
  const [retryingMessageId, setRetryingMessageId] = useState<string | null>(
    null,
  );

  // Keep scroll state in refs so scroll handlers stay synchronous and avoid
  // triggering re-renders.
  const vlistRef = useRef<VListHandle>(null);
  const scrollerElRef = useRef<HTMLElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composerWrapRef = useRef<HTMLElement>(null);
  const closedStatusRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const isPrependingRef = useRef(false);
  const isSendingRef = useRef(false);
  const initialJumpDoneRef = useRef(false);
  const lastLoadMoreAtRef = useRef(0);
  const newestMessageIdRef = useRef<string | null>(null);
  const [composerReserve, setComposerReserve] = useState(
    DEFAULT_COMPOSER_RESERVE_PX,
  );
  // Two independent booleans — see phase-02 §Architecture. The viewport
  // position (`isAwayFromBottom`) drives whether the latest control is shown;
  // the author/type-aware arrival flag (`hasUnseenLatest`) drives whether it is
  // emphasized as "Tin nhắn mới". Only threshold crossings update React state;
  // raw scroll distance stays in refs.
  const [isAwayFromBottom, setIsAwayFromBottom] = useState(false);
  const [hasUnseenLatest, setHasUnseenLatest] = useState(false);

  const {
    isBotMode: internalIsBotMode,
    needsClaim: internalNeedsClaim,
    canHumanReply: internalCanHumanReply,
    handleTakeover: internalHandleTakeover,
    handleForceBotReply: internalHandleForceBotReply,
    isChangingMode: internalIsChangingMode,
  } = useConversationActions(conversation);
  const isBotMode = isBotModeOverride ?? internalIsBotMode;
  const needsClaim = needsClaimOverride ?? internalNeedsClaim;
  const canHumanReply = canHumanReplyOverride ?? internalCanHumanReply;
  const handleTakeover = onTakeoverOverride ?? internalHandleTakeover;
  const handleForceBotReply = internalHandleForceBotReply;
  const isChangingMode = Boolean(
    isChangingModeOverride ?? internalIsChangingMode,
  );
  const [isForcingBotReply, setIsForcingBotReply] = useState(false);

  const handleForceBotReplyClick = async () => {
    if (isForcingBotReply) return;
    setIsForcingBotReply(true);
    try {
      await handleForceBotReply();
    } finally {
      setIsForcingBotReply(false);
    }
  };
  // Footer is always present for a selected conversation so the bottom row is a
  // stable boundary in every mode. Content is derived from existing state only.
  const showTakeoverNotice =
    showComposerTakeoverNotice && (isBotMode || needsClaim);
  const isClosedMode = !isBotMode && !needsClaim && !canHumanReply;
  const showComposerForm = canHumanReply;

  // Only an explicit takeover should move focus into the newly available
  // composer. Realtime mode changes must not interrupt the reader's focus.
  useEffect(() => {
    if (!takeoverFocusRequest) return;
    if (takeoverFocusRequest.conversationId !== conversationId) {
      setTakeoverFocusRequest(null);
      return;
    }
    if (!takeoverFocusRequest.settled || isChangingMode) return;
    setTakeoverFocusRequest(null);
    if (canHumanReply) textareaRef.current?.focus({ preventScroll: true });
  }, [takeoverFocusRequest, conversationId, canHumanReply, isChangingMode]);

  const handleExplicitTakeover = async () => {
    if (isChangingMode || takeoverFocusRequest) return;
    const request = { conversationId, settled: false };
    setTakeoverFocusRequest(request);
    try {
      await handleTakeover();
      setTakeoverFocusRequest((current) =>
        current === request ? { ...request, settled: true } : current,
      );
    } catch {
      // The action owns error feedback. Failed claims leave focus in place.
      setTakeoverFocusRequest((current) =>
        current === request ? null : current,
      );
    }
  };

  const scrollToNewest = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = scrollerElRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  // Server-confirm the optimistic unread clear.
  useEffect(() => {
    if (!conversationId) return;
    if (!conversation || (conversation.unread_count ?? 0) === 0) return;
    markConversationAsRead(operations, conversationId).catch(() => {});
  }, [conversationId, conversation, operations]);

  // Reset per-conversation scroll state on switch.
  useEffect(() => {
    initialJumpDoneRef.current = false;
    isAtBottomRef.current = true;
    isPrependingRef.current = false;
    newestMessageIdRef.current = null;
    lastLoadMoreAtRef.current = 0;
    setIsAwayFromBottom(false);
    setHasUnseenLatest(false);
  }, [conversationId]);

  // Initial snap-to-bottom when messages first arrive for a conversation.
  useEffect(() => {
    if (messages.length > 0 && !initialJumpDoneRef.current) {
      initialJumpDoneRef.current = true;
      // Double-RAF to let virtua measure + lay out before scrolling.
      requestAnimationFrame(() =>
        requestAnimationFrame(() => scrollToNewest()),
      );
    }
  }, [messages, scrollToNewest]);

  // Auto-scroll to bottom on new message IF the user is already at the bottom.
  // If they've scrolled up, reveal the latest control — emphasized only when
  // the new arrival is "unseen" (author/type-aware, per the phase-02 contract).
  // Own optimistic sends, their server echoes, system events, and history
  // prepends never count as unseen.
  const newestMessageId =
    messages.length > 0 ? messages[messages.length - 1].id : null;
  const newestMessage =
    messages.length > 0 ? messages[messages.length - 1] : null;
  useEffect(() => {
    if (!newestMessageId || !initialJumpDoneRef.current) {
      newestMessageIdRef.current = newestMessageId;
      return;
    }
    const prev = newestMessageIdRef.current;
    newestMessageIdRef.current = newestMessageId;
    if (prev === null || prev === newestMessageId) return;
    if (isPrependingRef.current) {
      // History prepend: keep the anchor, do not flash a false new-message cue.
      return;
    }
    const qualifiesAsUnseen =
      !!newestMessage && isUnseenWorthyArrival(newestMessage, identity?.id);
    if (isAtBottomRef.current) {
      setHasUnseenLatest(false);
      scrollToNewest();
    } else if (qualifiesAsUnseen) {
      setHasUnseenLatest(true);
    }
    // If the reader is away but the arrival is not unseen-worthy (e.g. own
    // optimistic send), the compact latest control still reflects position; we
    // just don't escalate to "Tin nhắn mới".
  }, [newestMessageId, newestMessage, identity?.id, scrollToNewest]);

  // Prefer reduced motion: jump instantly; otherwise smooth-scroll to latest.
  // Reacts to runtime OS setting changes via a matchMedia listener.
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    )
      return;
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = (e: MediaQueryListEvent) =>
      setPrefersReducedMotion(e.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  // Move focus to a stable, mode-appropriate target BEFORE the latest button
  // can unmount, so keyboard users never lose their place.
  const focusStableTarget = useCallback(() => {
    if (showComposerForm) {
      textareaRef.current?.focus({ preventScroll: true });
    } else if (showTakeoverNotice) {
      const btn = composerWrapRef.current?.querySelector<HTMLButtonElement>(
        ".inline-takeover-btn",
      );
      btn?.focus({ preventScroll: true });
    } else if (closedStatusRef.current) {
      closedStatusRef.current.focus({ preventScroll: true });
    }
  }, [showComposerForm, showTakeoverNotice]);

  const handleJumpToNewest = useCallback(() => {
    setHasUnseenLatest(false);
    isAtBottomRef.current = true;
    setIsAwayFromBottom(false);
    scrollToNewest(prefersReducedMotion ? "auto" : "smooth");
    focusStableTarget();
  }, [scrollToNewest, prefersReducedMotion, focusStableTarget]);

  // --- Composer auto-grow + reserve ---
  const syncComposerTextarea = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    const nextHeight = Math.min(
      textarea.scrollHeight,
      COMPOSER_TEXTAREA_MAX_HEIGHT,
    );
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY =
      textarea.scrollHeight > COMPOSER_TEXTAREA_MAX_HEIGHT ? "auto" : "hidden";
  }, []);

  useLayoutEffect(() => {
    syncComposerTextarea();
  }, [reply, canHumanReply, isBotMode, syncComposerTextarea]);

  useLayoutEffect(() => {
    // Footer is always rendered for a selected conversation. Recompute its
    // reserve (a virtua hint) on every mode/content swap and observe growth.
    const footer = composerWrapRef.current;
    if (!footer) {
      setComposerReserve(DEFAULT_COMPOSER_RESERVE_PX);
      return;
    }
    const update = () => {
      const next = Math.ceil(
        footer.getBoundingClientRect().height + COMPOSER_RESERVE_GAP_PX,
      );
      setComposerReserve((cur) => (cur === next ? cur : next));
      // A footer swap/growth shifts the scroller's clientHeight, which can move
      // the at-bottom threshold. Recompute the viewport-position state so the
      // latest control reflects reality without a manual scroll. Only a true
      // crossing to at-bottom clears the flags; an away reader stays away.
      const el = scrollerElRef.current;
      if (el) {
        const distanceFromBottom =
          el.scrollHeight - el.scrollTop - el.clientHeight;
        const atBottom = distanceFromBottom < CHAT_AT_BOTTOM_THRESHOLD_PX;
        isAtBottomRef.current = atBottom;
        if (atBottom) {
          setIsAwayFromBottom(false);
          setHasUnseenLatest(false);
        }
      }
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const obs = new ResizeObserver(update);
    obs.observe(footer);
    return () => obs.disconnect();
  }, [showComposerForm, showTakeoverNotice, isClosedMode]);

  // virtua writes its measured content height inside its item ResizeObserver.
  // Observing that shallower container with another ResizeObserver creates
  // skipped notifications in the same delivery loop. Follow its committed
  // layout changes after delivery instead, and coalesce scroll writes per frame.
  useEffect(() => {
    const el = scrollerElRef.current;
    if (!el || typeof MutationObserver === "undefined") return;
    const content = el.firstElementChild as HTMLElement | null;
    if (!content) return;
    let pendingFrame: number | null = null;
    const obs = new MutationObserver(() => {
      if (pendingFrame !== null) return;
      pendingFrame = requestAnimationFrame(() => {
        pendingFrame = null;
        if (isAtBottomRef.current && !isPrependingRef.current) {
          scrollToNewest();
        }
      });
    });
    obs.observe(content, {
      attributes: true,
      attributeFilter: ["style"],
      childList: true,
    });
    return () => {
      obs.disconnect();
      if (pendingFrame !== null) cancelAnimationFrame(pendingFrame);
    };
  }, [scrollToNewest, conversationId]);

  // --- Load-more (scroll up for older history) ---
  const handleLoadMore = useCallback(() => {
    if (
      !initialJumpDoneRef.current ||
      isLoadingMore ||
      !hasMore ||
      messages.length === 0
    )
      return;
    const now = performance.now();
    if (now - lastLoadMoreAtRef.current < 350) return;
    lastLoadMoreAtRef.current = now;
    isPrependingRef.current = true;
    void loadMore(messages[0].id).finally(() => {
      isPrependingRef.current = false;
    });
  }, [hasMore, isLoadingMore, messages, loadMore]);

  // --- virtua onScroll: at-bottom detection + top load-more ---
  const handleScroll = useCallback(
    (offset: number) => {
      const el = scrollerElRef.current;
      if (!el) return;
      const distanceFromBottom =
        el.scrollHeight - el.scrollTop - el.clientHeight;
      const wasAtBottom = isAtBottomRef.current;
      isAtBottomRef.current = distanceFromBottom < CHAT_AT_BOTTOM_THRESHOLD_PX;
      // Only threshold crossings update React state (rerender churn guard).
      if (isAtBottomRef.current && !wasAtBottom) {
        setIsAwayFromBottom(false);
        setHasUnseenLatest(false);
      } else if (!isAtBottomRef.current && wasAtBottom) {
        setIsAwayFromBottom(true);
      }
      // Top load-more: virtua fires onScroll with offset; near 0 = near top.
      if (
        offset < HISTORY_LOAD_TOP_THRESHOLD_PX &&
        initialJumpDoneRef.current
      ) {
        handleLoadMore();
      }
    },
    [handleLoadMore],
  );

  // One failure toast for both write paths. The channel-naming statuses pick
  // their copy per delivery channel (Messenger ≠ Zalo); the rest stay shared.
  const notifyReplyFailure = useCallback(
    (err: unknown) => {
      const status = isHumanReplyFailure(err) ? err.status : "error";
      notify(
        translate(
          replyFailureMessageKey(status, conversation?.channel_identity),
        ),
        { type: "error" },
      );
    },
    [conversation?.channel_identity, notify, translate],
  );

  // --- Send (optimistic) ---
  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = reply.trim();
    if (!trimmed || !canHumanReply || isChangingMode || isSendingRef.current)
      return;
    isSendingRef.current = true;
    const recruiterId = identity?.id != null ? String(identity.id) : "";
    const tempId = recruiterId ? insertOptimistic(trimmed, recruiterId) : "";
    const sentText = trimmed;
    setReply("");
    setIsSending(true);
    // A local send signals intent to return to latest; never label it unseen.
    setHasUnseenLatest(false);
    isAtBottomRef.current = true;
    setIsAwayFromBottom(false);
    try {
      await sendConversationReply(operations, conversationId, sentText);
    } catch (err: unknown) {
      notifyReplyFailure(err);
      if (tempId) markOptimisticFailed(tempId);
      // A 502 means the API persisted a failed delivery command. Keep its
      // bubble as the single retry target instead of placing duplicate text in
      // the composer. Other failures did not establish that durable message.
      if (!(isHumanReplyFailure(err) && err.httpStatus === 502)) {
        setReply(sentText);
      }
    } finally {
      isSendingRef.current = false;
      setIsSending(false);
    }
  };

  const retryConversation = useCallback(
    async (messageId: string) => {
      if (messageId.startsWith("optimistic-") || retryingMessageId) return;
      setRetryingMessageId(messageId);
      try {
        await retryConversationReply(operations, conversationId, messageId);
      } catch (err: unknown) {
        notifyReplyFailure(err);
      } finally {
        setRetryingMessageId((current) =>
          current === messageId ? null : current,
        );
      }
    },
    [conversationId, notifyReplyFailure, operations, retryingMessageId],
  );
  // Stable identity: the memoized bubble compares `onRetry`, so a callback
  // that changed with the in-flight retry id would re-render every message in
  // the thread each time one failed send is retried.
  const retryConversationRef = useRef(retryConversation);
  useEffect(() => {
    retryConversationRef.current = retryConversation;
  }, [retryConversation]);
  const handleRetryMessage = useCallback(
    (messageId: string) => retryConversationRef.current(messageId),
    [],
  );

  // One row per stored message, derived from the stored array itself. That
  // array is reused until a message actually changes, so this memo keys on a
  // value that really changes: an arrival re-derives the rows, while typing a
  // reply or settling a retry leaves every row's props untouched.
  const rows = useMemo(() => groupConversationMessages(messages), [messages]);
  // The display channel drives channel-aware failure copy on every bubble row;
  // resolved once per conversation instead of per row render.
  const channelProvider = useMemo(
    () => resolveConversationDisplayChannel(conversation?.channel_identity),
    [conversation?.channel_identity],
  );

  // --- Render ---

  return (
    <>
      <div
        className="chat-scroll-shell"
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
        aria-label="Luồng tin nhắn"
        aria-busy={isLoading}
        ref={(el) => {
          // Capture the actual scrollable element (virtua renders it inside the
          // VList wrapper). Query for the element that has overflow:auto/scroll.
          const scroller = el?.querySelector<HTMLElement>(".chat-scroller");
          scrollerElRef.current = scroller ?? null;
        }}
      >
        <VList
          ref={vlistRef}
          className="chat-scroller"
          style={
            {
              height: "100%",
              "--chat-composer-reserve": `${composerReserve}px`,
            } as CSSProperties
          }
          shift={isPrependingRef.current /* anchor on prepend (history load) */}
          onScroll={handleScroll}
        >
          {isLoadingMore && (
            <div className="chat-history-top-spacer">
              <LoadingState
                compact
                className="chat-history-loading"
                label="Đang tải tin nhắn cũ hơn…"
              />
            </div>
          )}
          {historyError && messages.length > 0 ? (
            <div
              className="chat-history-error tt-alert tt-alert-warning tt-alert-soft"
              role="status"
            >
              <span>Không tải được tin nhắn cũ hơn.</span>
              <Button
                type="button"
                size="sm"
                color="link-color"
                className="tt-btn tt-btn-sm tt-btn-outline"
                onPress={() => retryHistory(messages[0].id)}
              >
                {translate("crm.common.retry")}
              </Button>
            </div>
          ) : null}
          {messages.length === 0 && initialError ? (
            <div
              className="chat-empty chat-load-error tt-alert tt-alert-error tt-alert-soft"
              role="status"
            >
              <span>
                Không thể tải tin nhắn. Nội dung chưa được xác nhận là trống.
              </span>
              <Button
                className="tt-btn tt-btn-sm tt-btn-outline"
                type="button"
                size="sm"
                color="link-color"
                onPress={retryInitial}
              >
                {translate("crm.common.retry")}
              </Button>
            </div>
          ) : messages.length === 0 && isLoading ? (
            <LoadingState className="min-h-full" label="Đang tải tin nhắn…" />
          ) : null}
          {rows.map(({ message, kind, isGrouped }) => (
            <Fragment key={`${message.conversation_id}:${message.id}`}>
              <ChatMessageRow
                message={message}
                kind={kind}
                isGrouped={isGrouped}
                candidateAvatarUrl={candidateAvatarUrl}
                isRetrying={retryingMessageId === message.id}
                onRetry={handleRetryMessage}
                channelProvider={channelProvider}
              />
            </Fragment>
          ))}
        </VList>
        {/* Latest control: compact down arrow whenever the reader is away from
            the bottom; escalates to the stronger "Tin nhắn mới" label only when
            an author/type-aware unseen arrival occurred while away. */}
        {isAwayFromBottom ? (
          <Button
            size="sm"
            color={hasUnseenLatest ? "primary" : "secondary"}
            className={`uu-scope new-message-jump tt-btn tt-btn-sm${
              hasUnseenLatest ? " has-unseen tt-btn-primary" : ""
            }`}
            aria-label={
              hasUnseenLatest
                ? "Cuộn đến tin nhắn mới"
                : "Cuộn đến tin nhắn mới nhất"
            }
            onPress={handleJumpToNewest}
            iconTrailing={
              <svg className="icon new-message-jump-icon" aria-hidden="true">
                <use href="#i-chevron" />
              </svg>
            }
          >
            {hasUnseenLatest ? <span>Tin nhắn mới</span> : null}
          </Button>
        ) : null}
      </div>

      {/* The bottom row is always rendered for a selected conversation so it is
          a stable boundary in every mode. No position:fixed/overlay. */}
      <footer ref={composerWrapRef} className="composer-wrap">
        {composerToolbar ? (
          <div className="composer-controls">
            {composerToolbar}
            {showTakeoverNotice ? (
              <div className="composer-takeover-controls">
                {needsClaim ? (
                  <span className="composer-claim-hint">
                    Cần tiếp quản để trả lời.
                  </span>
                ) : null}
                <Button
                  type="button"
                  color="primary"
                  size="sm"
                  className="uu-scope inline-takeover-btn"
                  isDisabled={isChangingMode}
                  isLoading={isChangingMode}
                  showTextWhileLoading
                  onPress={handleExplicitTakeover}
                >
                  Tiếp quản
                </Button>
              </div>
            ) : null}
          </div>
        ) : null}
        {!composerToolbar && showTakeoverNotice && (
          <div className="handoff-note tt-alert tt-alert-info tt-alert-soft">
            <Bot className="icon" />
            <span>
              {needsClaim
                ? "Hội thoại cần nhân viên xác minh trước khi trả lời."
                : "Chatbot tự động trả lời."}
            </span>
            {isBotMode ? (
              <Button
                type="button"
                size="sm"
                color="primary"
                className="uu-scope inline-takeover-btn tt-btn tt-btn-sm tt-btn-outline"
                isDisabled={isForcingBotReply || isChangingMode}
                isLoading={isForcingBotReply}
                showTextWhileLoading
                onPress={handleForceBotReplyClick}
              >
                Cho bot trả lời
              </Button>
            ) : null}
            <Button
              type="button"
              size="sm"
              color="primary"
              className="uu-scope inline-takeover-btn tt-btn tt-btn-sm tt-btn-outline"
              isDisabled={isChangingMode}
              isLoading={isChangingMode}
              showTextWhileLoading
              onPress={handleExplicitTakeover}
            >
              Tiếp quản
            </Button>
          </div>
        )}
        {showComposerForm && (
          <form
            className={`composer ${!canHumanReply || isChangingMode ? "disabled" : ""}`}
            aria-busy={isSending || isChangingMode}
            onSubmit={handleSend}
          >
            <textarea
              ref={textareaRef}
              className="tt-textarea"
              rows={1}
              aria-label="Tin nhắn trả lời"
              aria-describedby={isMobile ? undefined : composerHintId}
              placeholder={canHumanReply ? "Nhập tin nhắn..." : "Chưa sẵn sàng"}
              disabled={!canHumanReply || isChangingMode || isSending}
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !isMobile &&
                  !e.nativeEvent.isComposing &&
                  e.keyCode !== 229
                ) {
                  e.preventDefault();
                  handleSend(e);
                }
              }}
            />
            <Button
              type="submit"
              size="sm"
              color="tertiary"
              className="uu-scope composer-action send"
              data-allow-tall
              aria-label="Gửi tin nhắn"
              isDisabled={
                !canHumanReply || isChangingMode || isSending || !reply.trim()
              }
              isLoading={isSending}
              iconLeading={
                <svg className="icon" aria-hidden="true">
                  <use href="#i-send" />
                </svg>
              }
            />
          </form>
        )}
        {showComposerForm && !isMobile ? (
          <p id={composerHintId} className="composer-keyboard-hint">
            Enter để gửi · Shift + Enter để xuống dòng
          </p>
        ) : null}
        {isClosedMode && (
          <div
            ref={closedStatusRef}
            className="closed-note"
            role="status"
            tabIndex={-1}
          >
            <Bot className="icon" aria-hidden="true" />
            <span>
              Hội thoại đã đóng. Không thể gửi tin nhắn cho người trò chuyện.
            </span>
          </div>
        )}
      </footer>
    </>
  );
};
