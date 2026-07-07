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
import type { Conversation, Message } from "../types";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import { HumanReplyError } from "@/lib/vfic/humanReplyService";
import { useConversationActions } from "./useConversationActions";
import { useConversationRealtime } from "./useConversationRealtime";
import { useConversationMessages, useConversationFlags } from "./messageStore";
import { Bot, Sparkles, UserRound } from "lucide-react";

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
};

const deliveryStatusLabel = (status?: Message["delivery_status"]) => {
  if (status === "failed") return "Gửi lỗi";
  if (status === "suppressed") return "Đã chặn";
  if (status === "sent") return "Đã gửi";
  return "";
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
  ({ message: m, kind, isGrouped }: ChatMessageRowProps) => {
    const textBlocks = useMemo(
      () => splitMessageTextBlocks(m.content),
      [m.content],
    );

    if (kind === "system" || kind === "event") {
      return (
        <div
          className={kind === "system" ? "day-marker" : "system-event"}
          data-message-id={m.id}
        >
          {kind === "event" ? <Sparkles className="icon" /> : null}
          <span>{m.content}</span>
        </div>
      );
    }

    const deliveryLabel = deliveryStatusLabel(m.delivery_status);
    const AvatarIcon = kind === "bot" ? Bot : UserRound;
    const avatar = !isGrouped ? (
      <span className="message-avatar">
        <AvatarIcon className="icon" />
      </span>
    ) : (
      <span
        className="message-avatar-placeholder"
        style={AVATAR_PLACEHOLDER_STYLE}
      />
    );
    const bubble = (
      <div className="bubble">
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
          </div>
          <span className="bubble-meta-inline">
            {kind !== "user" && deliveryLabel ? (
              <span
                className={`delivery-status ${m.delivery_status ?? "sent"}`}
              >
                {deliveryLabel}
              </span>
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
        className={`message-row ${kind} ${isGrouped ? "grouped" : ""}`}
        data-message-id={m.id}
      >
        {kind === "user" ? (
          <>
            {avatar}
            {bubble}
          </>
        ) : (
          <>
            {bubble}
            {avatar}
          </>
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
  isBotModeOverride?: boolean;
  canHumanReplyOverride?: boolean;
  onTakeoverOverride?: () => void;
  showComposerTakeoverNotice?: boolean;
}

export const ChatThread = ({
  conversationId,
  conversation,
  isBotModeOverride,
  canHumanReplyOverride,
  onTakeoverOverride,
  showComposerTakeoverNotice = true,
}: ChatThreadProps) => {
  // Message state lives in the normalized store (persists across conversation
  // switches). The hook drives data INTO the store; we read arrays out here.
  const messages = useConversationMessages(conversationId);
  const { isLoading, isLoadingMore, hasMore } =
    useConversationFlags(conversationId);
  const { loadMore, insertOptimistic, markOptimisticFailed } =
    useConversationRealtime(conversationId);
  const dataProvider = useDataProvider<CrmDataProvider>();
  const { identity } = useGetIdentity();
  const notify = useNotify();
  const translate = useTranslate();
  const [reply, setReply] = useState("");
  const [isSending, setIsSending] = useState(false);

  // Keep scroll state in refs so scroll handlers stay synchronous and avoid
  // triggering re-renders.
  const vlistRef = useRef<VListHandle>(null);
  const scrollerElRef = useRef<HTMLElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composerWrapRef = useRef<HTMLElement>(null);
  const isAtBottomRef = useRef(true);
  const isPrependingRef = useRef(false);
  const initialJumpDoneRef = useRef(false);
  const lastLoadMoreAtRef = useRef(0);
  const newestMessageIdRef = useRef<string | null>(null);
  const [composerReserve, setComposerReserve] = useState(
    DEFAULT_COMPOSER_RESERVE_PX,
  );
  const [hasNewerMessages, setHasNewerMessages] = useState(false);

  const {
    isBotMode: internalIsBotMode,
    canHumanReply: internalCanHumanReply,
    handleTakeover: internalHandleTakeover,
  } = useConversationActions(conversation);
  const isBotMode = isBotModeOverride ?? internalIsBotMode;
  const canHumanReply = canHumanReplyOverride ?? internalCanHumanReply;
  const handleTakeover = onTakeoverOverride ?? internalHandleTakeover;
  const showTakeoverNotice = showComposerTakeoverNotice && isBotMode;
  const showComposerForm = !isBotMode;
  const showComposerFooter = showTakeoverNotice || showComposerForm;

  const scrollToNewest = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = scrollerElRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  // Server-confirm the optimistic unread clear.
  useEffect(() => {
    if (!conversationId) return;
    if (!conversation || (conversation.unread_count ?? 0) === 0) return;
    dataProvider.markAsRead(conversationId).catch(() => {});
  }, [conversationId, conversation, dataProvider]);

  // Reset per-conversation scroll state on switch.
  useEffect(() => {
    initialJumpDoneRef.current = false;
    isAtBottomRef.current = true;
    isPrependingRef.current = false;
    newestMessageIdRef.current = null;
    lastLoadMoreAtRef.current = 0;
    setHasNewerMessages(false);
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
  // If they've scrolled up, show the "new messages" jump button instead.
  const newestMessageId =
    messages.length > 0 ? messages[messages.length - 1].id : null;
  useEffect(() => {
    if (!newestMessageId || !initialJumpDoneRef.current) {
      newestMessageIdRef.current = newestMessageId;
      return;
    }
    const prev = newestMessageIdRef.current;
    newestMessageIdRef.current = newestMessageId;
    if (prev === null || prev === newestMessageId) return;
    if (isAtBottomRef.current && !isPrependingRef.current) {
      setHasNewerMessages(false);
      scrollToNewest();
    } else if (!isPrependingRef.current) {
      setHasNewerMessages(true);
    }
  }, [newestMessageId, scrollToNewest]);

  const handleJumpToNewest = useCallback(() => {
    setHasNewerMessages(false);
    isAtBottomRef.current = true;
    scrollToNewest("smooth");
  }, [scrollToNewest]);

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
    if (!showComposerFooter) {
      setComposerReserve(0);
      return;
    }
    const footer = composerWrapRef.current;
    if (!footer) return;
    const update = () => {
      const next = Math.ceil(
        footer.getBoundingClientRect().height + COMPOSER_RESERVE_GAP_PX,
      );
      setComposerReserve((cur) => (cur === next ? cur : next));
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const obs = new ResizeObserver(update);
    obs.observe(footer);
    return () => obs.disconnect();
  }, [showComposerFooter, showTakeoverNotice]);

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
      if (isAtBottomRef.current && !wasAtBottom) {
        setHasNewerMessages(false);
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
    if (!trimmed || !canHumanReply) return;
    const recruiterId = identity?.id != null ? String(identity.id) : "";
    const tempId = recruiterId ? insertOptimistic(trimmed, recruiterId) : "";
    const sentText = trimmed;
    setReply("");
    setIsSending(true);
    try {
      await dataProvider.sendHumanReply(conversationId, sentText);
    } catch (err: unknown) {
      const status = err instanceof HumanReplyError ? err.status : "error";
      notify(translate(`resources.conversations.reply.${status}`), {
        type: "error",
      });
      if (tempId) markOptimisticFailed(tempId);
      setReply(sentText);
    } finally {
      setIsSending(false);
    }
  };

  // --- Render ---

  // Stable itemContent for virtua. Group consecutive same-kind messages.
  const renderMessage = useCallback(
    (index: number, m: Message) => {
      const kind = classify(m);
      const prevMsg = index > 0 ? messages[index - 1] : null;
      const prevKind = prevMsg ? classify(prevMsg) : null;
      const isGrouped = prevKind === kind;
      return <ChatMessageRow message={m} kind={kind} isGrouped={isGrouped} />;
    },
    [messages],
  );

  return (
    <>
      <div
        className="chat-scroll-shell"
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
              <div
                className="day-marker"
                style={{ margin: "8px 0", background: "transparent" }}
              >
                <span>Đang tải tin nhắn cũ hơn...</span>
              </div>
            </div>
          )}
          {messages.length === 0 && !isLoading ? (
            <div className="chat-empty" role="status">
              <span>Chưa có tin nhắn nào. Bắt đầu trò chuyện!</span>
            </div>
          ) : messages.length === 0 && isLoading ? (
            <div className="chat-empty" role="status">
              <span>Đang tải tin nhắn...</span>
            </div>
          ) : null}
          {messages.map((m, i) => (
            <Fragment key={`${m.conversation_id}:${m.id}`}>
              {renderMessage(i, m)}
            </Fragment>
          ))}
        </VList>
        {hasNewerMessages ? (
          <button
            type="button"
            className="new-message-jump"
            aria-label="Cuộn đến tin nhắn mới nhất"
            onClick={handleJumpToNewest}
          >
            <span>Tin nhắn mới</span>
            <svg className="icon new-message-jump-icon">
              <use href="#i-chevron" />
            </svg>
          </button>
        ) : null}
      </div>

      {showComposerFooter && (
        <footer ref={composerWrapRef} className="composer-wrap">
          {showTakeoverNotice && (
            <div className="handoff-note">
              <Bot className="icon" />
              <span>Đang dùng ChatBot cho cuộc trò chuyện này.</span>
              <button
                type="button"
                className="inline-takeover-btn"
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
                rows={1}
                placeholder={
                  canHumanReply ? "Nhập tin nhắn..." : "Chưa sẵn sàng"
                }
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
                className="composer-action send"
                aria-label="Gửi tin nhắn"
                disabled={!canHumanReply || isSending || !reply.trim()}
              >
                <svg className="icon">
                  <use href="#i-send" />
                </svg>
              </button>
            </form>
          )}
        </footer>
      )}
    </>
  );
};
