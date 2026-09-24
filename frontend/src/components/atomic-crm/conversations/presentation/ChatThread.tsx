import {
  forwardRef,
  Fragment,
  useEffect,
  useLayoutEffect,
  useState,
  useRef,
  useCallback,
  useMemo,
  memo,
  type CSSProperties,
  type HTMLAttributes,
} from "react";
import { VList, type VListHandle } from "virtua";
import {
  useDataProvider,
  useGetIdentity,
  useNotify,
  useTranslate,
} from "ra-core";
import type { Conversation, Message } from "../../types";
import {
  isHumanReplyFailure,
  markConversationAsRead,
  retryConversationReply,
  sendConversationReply,
} from "../application/conversation-operations";
import type { CrmDataProvider } from "../../providers/rest/dataProvider";
import { useConversationActions } from "./use-conversation-actions";
import { useConversationRealtime } from "./use-conversation-realtime";
import {
  useConversationMessages,
  useConversationFlags,
} from "./conversation-message-state";
import { LeadAvatar } from "../LeadAvatar";
import { LoadingState } from "../../misc/LoadingState";
import { Bot, Sparkles } from "lucide-react";

// ChatThread is the reusable message thread + composer. It owns the realtime
// subscription, the virtualised scroller (with all the snap / load-more arming
// logic), the reply composer and the bot→human takeover affordance. It renders a
// FRAGMENT (scroll shell + <footer/>) so the host shell lays out the scroller
// (1fr) and composer (auto) — the inbox center-panel grid does this. Styling
// comes from the .inbox-bg-container scope in inbox.css.

const classify = (
  msg: Message,
): "user" | "bot" | "agent" | "system" | "event" => {
  if (msg.type === "system") return "system";
  if (msg.type === "inbound") return "user";
  if (msg.data?.recruiter_id) return "agent";
  return "bot";
};

/**
 * Phase-02 unseen-content contract. The strong "Tin nhắn mới" emphasis applies
 * only to arrivals a reader can't anticipate: candidate inbound, bot replies,
 * and replies from *other* recruiters. The current recruiter's own optimistic
 * send (intent to go to latest), its server echo, system events, and history
 * prepends never qualify. Author/type is the discriminator — not id change.
 *
 * Exported for focused unit testing of the contract.
 */
export const isUnseenWorthyArrival = (
  msg: Message,
  currentRecruiterId: string | number | null | undefined,
): boolean => {
  if (msg.id.startsWith("optimistic-")) return false;
  if (msg.type === "system") return false;
  if (msg.type === "inbound") return true;
  // Outbound with a recruiter_id authored by someone else qualifies; authored
  // by the current recruiter (server echo of their own send) does not.
  const authorId = msg.data?.recruiter_id;
  if (!authorId) return true; // bot reply
  if (currentRecruiterId == null) return true;
  return String(authorId) !== String(currentRecruiterId);
};

const formatTime = (iso?: string) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
};

const COMPOSER_TEXTAREA_MAX_HEIGHT = 120;
const DEFAULT_COMPOSER_RESERVE_PX = 104;
const COMPOSER_RESERVE_GAP_PX = 16;
// Distance from the bottom (px) within which auto-scroll is allowed.
const CHAT_AT_BOTTOM_THRESHOLD_PX = 96;
// Distance from the top (px) within which we trigger history load-more.
const HISTORY_LOAD_TOP_THRESHOLD_PX = 100;
const AVATAR_PLACEHOLDER_STYLE: CSSProperties = { width: 32 };
const MESSAGE_TEXT_CHUNK_CHARS = 320;

type MessageKind = ReturnType<typeof classify>;

type ChatMessageRowProps = {
  message: Message;
  kind: MessageKind;
  isGrouped: boolean;
  candidateAvatarUrl?: string | null;
  isRetrying?: boolean;
  onRetry?: (messageId: string) => void;
};

const deliveryStatusLabel = (status?: Message["delivery_status"]) => {
  if (status === "failed") return "Gửi lỗi";
  if (status === "send_unknown") return "Chưa xác nhận gửi";
  if (status === "suppressed") return "Đã chặn";
  if (status === "sent") return "Đã gửi";
  return "";
};

const deliveryRetryLabel = (attempts?: number) => {
  if (attempts == null || attempts <= 1) return "";
  const retries = attempts - 1;
  return `Đã thử lại ${retries} lần`;
};

/**
 * Map a failed/unknown send's backend `external_error` to a short Vietnamese
 * reason, so a "Gửi lỗi" bubble is diagnosable instead of blank when the
 * attempted reply content is empty/unavailable. Mirrors the provider/network
 * taxonomy used elsewhere in the CRM (vietnameseCrmMessages.reply.*), in Vietnamese.
 */
const failureReasonLabel = (m: Message): string => {
  if (m.delivery_status !== "failed" && m.delivery_status !== "send_unknown") {
    return "";
  }
  const reason = (m.external_error ?? "").toLowerCase();
  if (!reason) return "";
  if (
    reason.includes("timeout") ||
    reason.includes("connect") ||
    reason.includes("network")
  ) {
    return "Lỗi kết nối mạng";
  }
  return "Zalo từ chối tin nhắn";
};

const splitLongTextLine = (line: string) => {
  if (line.length <= MESSAGE_TEXT_CHUNK_CHARS) return [line];

  const chunks: string[] = [];
  let remaining = line;
  while (remaining.length > MESSAGE_TEXT_CHUNK_CHARS) {
    const windowText = remaining.slice(0, MESSAGE_TEXT_CHUNK_CHARS);
    const sentenceBreak = Math.max(
      windowText.lastIndexOf(". "),
      windowText.lastIndexOf("! "),
      windowText.lastIndexOf("? "),
      windowText.lastIndexOf("; "),
      windowText.lastIndexOf(", "),
    );
    const splitAt =
      sentenceBreak > MESSAGE_TEXT_CHUNK_CHARS * 0.55
        ? sentenceBreak + 1
        : MESSAGE_TEXT_CHUNK_CHARS;
    chunks.push(remaining.slice(0, splitAt).trim());
    remaining = remaining.slice(splitAt).trim();
  }
  if (remaining) chunks.push(remaining);
  return chunks;
};

const splitMessageTextBlocks = (content: string) => {
  const blocks = content
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .flatMap((line) => {
      const trimmed = line.trim();
      return trimmed ? splitLongTextLine(trimmed) : [""];
    });

  return blocks.length > 0 ? blocks : [""];
};

const ChatItemList = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, children, ...props }, ref) => (
    <div
      {...props}
      ref={ref}
      className={["chat-item-list", className].filter(Boolean).join(" ")}
    >
      {children}
    </div>
  ),
);
ChatItemList.displayName = "ChatItemList";

const ChatMessageRow = memo(
  ({
    message: m,
    kind,
    isGrouped,
    candidateAvatarUrl,
    isRetrying = false,
    onRetry,
  }: ChatMessageRowProps) => {
    const translate = useTranslate();
    const textBlocks = useMemo(
      () => splitMessageTextBlocks(m.content),
      [m.content],
    );

    if (kind === "system") {
      return (
        <div className="system-message" data-message-id={m.id}>
          <span>{m.content}</span>
        </div>
      );
    }

    if (kind === "event") {
      return (
        <div className="system-event" data-message-id={m.id}>
          <Sparkles className="icon" />
          <span>{m.content}</span>
        </div>
      );
    }

    const deliveryLabel = deliveryStatusLabel(m.delivery_status);
    const retryLabel = deliveryRetryLabel(m.delivery_attempts);
    const canRetry =
      kind === "agent" &&
      m.delivery_status === "failed" &&
      !m.id.startsWith("optimistic-");
    // A failed send whose reply body is empty (e.g. an empty candidate that
    // slipped through) would render a blank bubble. Surface the failure reason
    // instead so the "Gửi lỗi" row always tells the recruiter what happened.
    const failureReason = failureReasonLabel(m);
    const hasText = textBlocks.some((block) => block && block.trim());
    const avatar =
      kind === "user" ? (
        !isGrouped ? (
          <LeadAvatar
            src={candidateAvatarUrl}
            className="message-avatar"
            iconSize={16}
            alt="Ảnh đại diện người trò chuyện"
          />
        ) : (
          <span
            className="message-avatar-placeholder"
            style={AVATAR_PLACEHOLDER_STYLE}
          />
        )
      ) : null;
    const bubble = (
      <div className="bubble tt-chat-bubble">
        <div className="bubble-content">
          <div className="message-text">
            {textBlocks.map((block, index) =>
              block ? (
                <p className="message-text-block" key={`${index}-${block}`}>
                  {block}
                </p>
              ) : (
                <span
                  aria-hidden="true"
                  className="message-text-break"
                  key={`break-${index}`}
                />
              ),
            )}
            {failureReason && !hasText ? (
              <p className="message-text-block delivery-error-detail">
                {failureReason}
              </p>
            ) : null}
          </div>
          <span className="bubble-meta-inline">
            {kind !== "user" && deliveryLabel ? (
              <span
                className={`delivery-status ${m.delivery_status ?? "sent"}`}
              >
                {deliveryLabel}
              </span>
            ) : null}
            {kind !== "user" && retryLabel ? (
              <span className="delivery-retry-count">{retryLabel}</span>
            ) : null}
            {canRetry ? (
              <button
                type="button"
                className="delivery-retry-button"
                disabled={isRetrying}
                onClick={() => onRetry?.(m.id)}
              >
                {isRetrying
                  ? translate("crm.common.retrying")
                  : translate("crm.common.retry")}
              </button>
            ) : null}
            <span className="bubble-time-inline">
              {formatTime(m.created_at)}
            </span>
          </span>
        </div>
      </div>
    );

    return (
      <div
        className={`message-row tt-chat ${kind === "user" ? "tt-chat-start" : "tt-chat-end"} ${kind} ${isGrouped ? "grouped" : ""}`}
        data-message-id={m.id}
      >
        {kind === "user" ? (
          <>
            {avatar}
            {bubble}
          </>
        ) : (
          bubble
        )}
      </div>
    );
  },
);
ChatMessageRow.displayName = "ChatMessageRow";

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
  onTakeoverOverride?: () => void;
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
  const operations = useDataProvider<CrmDataProvider>();
  const { identity } = useGetIdentity();
  const notify = useNotify();
  const translate = useTranslate();
  const [reply, setReply] = useState("");
  const [isSending, setIsSending] = useState(false);
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
  } = useConversationActions(conversation);
  const isBotMode = isBotModeOverride ?? internalIsBotMode;
  const needsClaim = needsClaimOverride ?? internalNeedsClaim;
  const canHumanReply = canHumanReplyOverride ?? internalCanHumanReply;
  const handleTakeover = onTakeoverOverride ?? internalHandleTakeover;
  // Footer is always present for a selected conversation so the bottom row is a
  // stable boundary in every mode. Content is derived from existing state only.
  const showTakeoverNotice =
    showComposerTakeoverNotice && (isBotMode || needsClaim);
  const isClosedMode = !isBotMode && !needsClaim && !canHumanReply;
  const showComposerForm = canHumanReply;

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

  // Re-snap to bottom on non-message size changes (composer grow, image load)
  // only when the user is already at the bottom.
  useEffect(() => {
    const el = scrollerElRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const content = el.firstElementChild as HTMLElement | null;
    if (!content) return;
    const obs = new ResizeObserver(() => {
      if (isAtBottomRef.current && !isPrependingRef.current) {
        scrollToNewest();
      }
    });
    obs.observe(content);
    return () => obs.disconnect();
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

  // --- Send (optimistic) ---
  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = reply.trim();
    if (!trimmed || !canHumanReply || isSendingRef.current) return;
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
      const status = isHumanReplyFailure(err) ? err.status : "error";
      notify(translate(`resources.conversations.reply.${status}`), {
        type: "error",
      });
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

  const handleRetryMessage = useCallback(
    async (messageId: string) => {
      if (messageId.startsWith("optimistic-") || retryingMessageId) return;
      setRetryingMessageId(messageId);
      try {
        await retryConversationReply(operations, conversationId, messageId);
      } catch (err: unknown) {
        const status = isHumanReplyFailure(err) ? err.status : "error";
        notify(translate(`resources.conversations.reply.${status}`), {
          type: "error",
        });
      } finally {
        setRetryingMessageId((current) =>
          current === messageId ? null : current,
        );
      }
    },
    [conversationId, notify, operations, retryingMessageId, translate],
  );

  // --- Render ---

  // Stable itemContent for virtua. Group consecutive same-kind messages.
  const renderMessage = useCallback(
    (index: number, m: Message) => {
      const kind = classify(m);
      const prevMsg = index > 0 ? messages[index - 1] : null;
      const prevKind = prevMsg ? classify(prevMsg) : null;
      const isGrouped = prevKind === kind;
      return (
        <ChatMessageRow
          message={m}
          kind={kind}
          isGrouped={isGrouped}
          candidateAvatarUrl={candidateAvatarUrl}
          isRetrying={retryingMessageId === m.id}
          onRetry={handleRetryMessage}
        />
      );
    },
    [candidateAvatarUrl, handleRetryMessage, messages, retryingMessageId],
  );

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
              <button
                type="button"
                className="tt-btn tt-btn-sm tt-btn-outline"
                onClick={() => retryHistory(messages[0].id)}
              >
                {translate("crm.common.retry")}
              </button>
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
              <button
                className="tt-btn tt-btn-sm tt-btn-outline"
                type="button"
                onClick={retryInitial}
              >
                {translate("crm.common.retry")}
              </button>
            </div>
          ) : messages.length === 0 && isLoading ? (
            <LoadingState className="min-h-full" label="Đang tải tin nhắn…" />
          ) : null}
          {messages.map((m, i) => (
            <Fragment key={`${m.conversation_id}:${m.id}`}>
              {renderMessage(i, m)}
            </Fragment>
          ))}
        </VList>
        {/* Latest control: compact down arrow whenever the reader is away from
            the bottom; escalates to the stronger "Tin nhắn mới" label only when
            an author/type-aware unseen arrival occurred while away. */}
        {isAwayFromBottom ? (
          <button
            type="button"
            className={`new-message-jump tt-btn tt-btn-sm${hasUnseenLatest ? " has-unseen tt-btn-primary" : ""}`}
            aria-label={
              hasUnseenLatest
                ? "Cuộn đến tin nhắn mới"
                : "Cuộn đến tin nhắn mới nhất"
            }
            onClick={handleJumpToNewest}
          >
            {hasUnseenLatest ? <span>Tin nhắn mới</span> : null}
            <svg className="icon new-message-jump-icon" aria-hidden="true">
              <use href="#i-chevron" />
            </svg>
          </button>
        ) : null}
      </div>

      {/* The bottom row is always rendered for a selected conversation so it is
          a stable boundary in every mode. No position:fixed/overlay. */}
      <footer ref={composerWrapRef} className="composer-wrap">
        {showTakeoverNotice && (
          <div className="handoff-note tt-alert tt-alert-info tt-alert-soft">
            <Bot className="icon" />
            <span>
              {needsClaim
                ? "Hội thoại cần nhân viên xác minh trước khi trả lời."
                : "Đang dùng ChatBot cho cuộc trò chuyện này."}
            </span>
            <button
              type="button"
              className="inline-takeover-btn tt-btn tt-btn-sm tt-btn-outline"
              onClick={handleTakeover}
            >
              Tiếp quản
            </button>
          </div>
        )}
        {showComposerForm && (
          <form
            className={`composer ${!canHumanReply ? "disabled" : ""}`}
            onSubmit={handleSend}
          >
            <textarea
              ref={textareaRef}
              className="tt-textarea"
              rows={1}
              placeholder={canHumanReply ? "Nhập tin nhắn..." : "Chưa sẵn sàng"}
              disabled={!canHumanReply || isSending}
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend(e);
                }
              }}
            />
            <button
              type="submit"
              className="composer-action send tt-btn tt-btn-primary tt-btn-circle text-primary-foreground"
              aria-label="Gửi tin nhắn"
              disabled={!canHumanReply || isSending || !reply.trim()}
            >
              <svg className="icon" aria-hidden="true">
                <use href="#i-send" />
              </svg>
            </button>
          </form>
        )}
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
