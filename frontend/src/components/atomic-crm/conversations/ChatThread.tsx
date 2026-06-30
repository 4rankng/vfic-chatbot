import {
  forwardRef,
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
import {
  Virtuoso,
  type SizeFunction,
  type VirtuosoHandle,
} from "react-virtuoso";
import { useDataProvider, useNotify, useTranslate } from "ra-core";
import type { Conversation, Message } from "../types";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import { HumanReplyError } from "@/lib/vfic/humanReplyService";
import { useConversationActions } from "./useConversationActions";
import { useConversationRealtime } from "./useConversationRealtime";
import {
  shouldPrefetchOlderMessages,
  shouldTrapEdgeWheel,
} from "./chatEdgeScroll";
import {
  measuredOrEstimatedMessageRowHeight,
} from "./chatScrollIndex";
import { Bot, Sparkles, UserRound } from "lucide-react";

// ChatThread is the reusable, shell-agnostic message thread + composer. It owns
// the realtime subscription, the virtualised scroller (with all the snap /
// load-more arming logic), the reply composer and the bot→human takeover
// affordance. It renders a FRAGMENT (scroll shell + <footer/>) so the host
// shell lays out the scroller (1fr) and composer (auto) — the inbox center-panel
// grid and the lead-page .chat-surface grid both do this. Styling comes from the
// .chat-surface scope in inbox.css (which also matches the inbox's own
// .inbox-bg-container), so the thread looks identical in either shell.

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
const DEFAULT_CHAT_ITEM_HEIGHT_PX = 96;
const HISTORY_PREFETCH_DISTANCE_PX = 1;
const CHAT_AT_BOTTOM_THRESHOLD_PX = 96;
const CHAT_AT_TOP_THRESHOLD_PX = 48;
const VIRTUOSO_INCREASE_VIEWPORT_BY = { top: 2400, bottom: 800 };
const VIRTUOSO_MIN_OVERSCAN_ITEM_COUNT = { top: 8, bottom: 4 };
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
  const {
    messages,
    isLoading,
    isLoadingMore,
    hasMore,
    firstItemIndex,
    loadMore,
  } = useConversationRealtime(conversationId);
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const translate = useTranslate();
  const [reply, setReply] = useState("");
  const [isSending, setIsSending] = useState(false);
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composerWrapRef = useRef<HTMLElement>(null);
  const scrollerElRef = useRef<HTMLElement | null>(null);
  const detachScrollerListenersRef = useRef<(() => void) | null>(null);
  const measuredMessageHeightsRef = useRef(new Map<string, number>());
  const initialJumpDoneRef = useRef(false);
  const initialBottomSettleUntilRef = useRef(0);
  const initialBottomSettleRafRef = useRef<number | null>(null);
  const lastScrollTopRef = useRef(0);
  const lastLoadMoreAtRef = useRef(0);
  const isAtBottomRef = useRef(true);
  const isPrependingHistoryRef = useRef(false);
  const newestMessageIdRef = useRef<string | null>(null);
  const [composerReserve, setComposerReserve] = useState(
    DEFAULT_COMPOSER_RESERVE_PX,
  );
  const [hasNewerMessages, setHasNewerMessages] = useState(false);
  const visibleMessages = useMemo(
    () =>
      conversationId
        ? messages.filter((message) => message.conversation_id === conversationId)
        : [],
    [conversationId, messages],
  );
  // Load older messages only on a genuine upward scroll — not merely because
  // the top happens to be visible (which is the case the moment a thread opens,
  // when the initial page fits the viewport, and would otherwise auto-fetch the
  // whole history). Armed by the scroll listener below, disarmed after each
  // page so one scroll-up = one page and the list can never run away.
  const readyForMoreRef = useRef(false);
  const loadOlderFromTopRef = useRef<() => void>(() => {
    /* assigned below after the loader callback is created */
  });

  const {
    isBotMode: internalIsBotMode,
    canHumanReply: internalCanHumanReply,
    handleTakeover: internalHandleTakeover,
  } = useConversationActions(conversation);
  const isBotMode = isBotModeOverride ?? internalIsBotMode;
  const canHumanReply = canHumanReplyOverride ?? internalCanHumanReply;
  const handleTakeover = onTakeoverOverride ?? internalHandleTakeover;

  const scrollToNewest = useCallback((behavior: "auto" | "smooth" = "auto") => {
    virtuosoRef.current?.scrollToIndex({
      index: "LAST",
      align: "end",
      behavior,
    });
    if (behavior === "auto") {
      requestAnimationFrame(() => {
        const scrollerEl = scrollerElRef.current;
        if (!scrollerEl) return;
        scrollerEl.scrollTop = scrollerEl.scrollHeight;
        lastScrollTopRef.current = scrollerEl.scrollTop;
      });
    }
  }, []);

  const scheduleScrollToNewest = useCallback(() => {
    if (initialBottomSettleRafRef.current !== null) {
      cancelAnimationFrame(initialBottomSettleRafRef.current);
    }

    initialBottomSettleRafRef.current = requestAnimationFrame(() => {
      initialBottomSettleRafRef.current = null;
      scrollToNewest();
    });
  }, [scrollToNewest]);

  // Server-confirm the optimistic unread clear from the inbox list. Skips the
  // round-trip when nothing is unread, and re-fires if a realtime inbound bumps
  // the counter while the recruiter is viewing the thread. vfic_mark_read resets
  // unread_count without touching updated_at (no inbox re-sort).
  useEffect(() => {
    if (!conversationId) return;
    if (!conversation || (conversation.unread_count ?? 0) === 0) return;
    dataProvider.markAsRead(conversationId).catch(() => {
      /* non-fatal: badge re-syncs on the next list load */
    });
  }, [conversationId, conversation, dataProvider]);

  // Reset per-conversation state so each thread opens at its newest message.
  useEffect(() => {
    initialJumpDoneRef.current = false;
    initialBottomSettleUntilRef.current = 0;
    if (initialBottomSettleRafRef.current !== null) {
      cancelAnimationFrame(initialBottomSettleRafRef.current);
      initialBottomSettleRafRef.current = null;
    }
    readyForMoreRef.current = false;
    isAtBottomRef.current = true;
    isPrependingHistoryRef.current = false;
    newestMessageIdRef.current = null;
    lastScrollTopRef.current = 0;
    lastLoadMoreAtRef.current = 0;
    setHasNewerMessages(false);
  }, [conversationId]);

  // Snap to the newest message instantly when a conversation opens, then let
  // Virtuoso's followOutput handle subsequent appends only when the user is
  // already at the bottom. Very tall bubbles can be measured after the first
  // snap, so totalListHeightChanged keeps the initial open pinned briefly.
  useEffect(() => {
    if (visibleMessages.length > 0 && !initialJumpDoneRef.current) {
      initialJumpDoneRef.current = true;
      initialBottomSettleUntilRef.current = performance.now() + 800;
      scrollToNewest();
      scheduleScrollToNewest();
    }
  }, [visibleMessages, scheduleScrollToNewest, scrollToNewest]);

  const handleTotalListHeightChanged = useCallback(() => {
    if (!initialJumpDoneRef.current) return;
    if (isPrependingHistoryRef.current) return;
    if (performance.now() > initialBottomSettleUntilRef.current) return;
    if (readyForMoreRef.current) return;
    scheduleScrollToNewest();
  }, [scheduleScrollToNewest]);

  const newestMessageId = visibleMessages[visibleMessages.length - 1]?.id ?? null;
  useEffect(() => {
    if (!newestMessageId) {
      newestMessageIdRef.current = null;
      return;
    }

    const previousNewestMessageId = newestMessageIdRef.current;
    newestMessageIdRef.current = newestMessageId;
    if (
      previousNewestMessageId === null ||
      previousNewestMessageId === newestMessageId ||
      !initialJumpDoneRef.current
    ) {
      return;
    }

    if (isAtBottomRef.current) {
      setHasNewerMessages(false);
      scheduleScrollToNewest();
      return;
    }

    if (!isPrependingHistoryRef.current) {
      setHasNewerMessages(true);
    }
  }, [newestMessageId, scheduleScrollToNewest]);

  const handleJumpToNewest = useCallback(() => {
    setHasNewerMessages(false);
    isAtBottomRef.current = true;
    scrollToNewest("smooth");
  }, [scrollToNewest]);

  const messageHeightEstimates = useMemo(
    () =>
      visibleMessages.map((message) =>
        measuredOrEstimatedMessageRowHeight(
          message,
          measuredMessageHeightsRef.current,
        ),
      ),
    [visibleMessages],
  );

  const measureMessageItem = useCallback<SizeFunction>((el, field) => {
    const rect = el.getBoundingClientRect();
    const measured = Math.ceil(
      field === "offsetWidth" ? rect.width : rect.height,
    );
    if (field === "offsetHeight" && measured > 0) {
      const messageEl = el.querySelector<HTMLElement>("[data-message-id]");
      const messageId = messageEl?.dataset.messageId;
      if (messageId) {
        measuredMessageHeightsRef.current.set(messageId, measured);
      }
    }
    return measured;
  }, []);

  const loadOlderFromTop = useCallback(() => {
    if (!initialJumpDoneRef.current) return;
    if (!readyForMoreRef.current) return;
    if (isLoadingMore) return;
    if (!hasMore || visibleMessages.length === 0) return;

    const now = performance.now();
    if (now - lastLoadMoreAtRef.current < 350) return;
    lastLoadMoreAtRef.current = now;

    readyForMoreRef.current = false;
    isPrependingHistoryRef.current = true;
    void loadMore(visibleMessages[0].id).then(() => {
      isPrependingHistoryRef.current = false;
    });
  }, [
    hasMore,
    isLoadingMore,
    visibleMessages,
    loadMore,
  ]);

  useEffect(() => {
    loadOlderFromTopRef.current = loadOlderFromTop;
  }, [loadOlderFromTop]);

  useEffect(
    () => () => {
      if (initialBottomSettleRafRef.current !== null) {
        cancelAnimationFrame(initialBottomSettleRafRef.current);
      }
    },
    [],
  );

  useLayoutEffect(() => {
    const footer = composerWrapRef.current;
    if (!footer) return;

    const updateComposerReserve = () => {
      const nextReserve = Math.ceil(
        footer.getBoundingClientRect().height + COMPOSER_RESERVE_GAP_PX,
      );
      setComposerReserve((currentReserve) =>
        currentReserve === nextReserve ? currentReserve : nextReserve,
      );
    };

    updateComposerReserve();
    if (typeof ResizeObserver === "undefined") return;

    const observer = new ResizeObserver(updateComposerReserve);
    observer.observe(footer);
    return () => observer.disconnect();
  }, [showComposerTakeoverNotice, isBotMode]);

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

  useEffect(() => {
    const onResize = () => syncComposerTextarea();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [syncComposerTextarea]);

  const handleAtBottomStateChange = useCallback((atBottom: boolean) => {
    isAtBottomRef.current = atBottom;
    if (atBottom) {
      readyForMoreRef.current = false;
      setHasNewerMessages(false);
    }
  }, []);

  // Arm "load more" only after a genuine upward scroll. A freshly opened
  // thread parks at the newest message, so top visibility alone must not fetch
  // history.
  const setScrollerRef = useCallback(
    (el: HTMLElement | Window | null) => {
      detachScrollerListenersRef.current?.();
      detachScrollerListenersRef.current = null;

      const scrollerEl = el instanceof HTMLElement ? el : null;
      scrollerElRef.current = scrollerEl;
      if (!scrollerEl) return;

      lastScrollTopRef.current = scrollerEl.scrollTop;
      const onScroll = () => {
        const previousTop = lastScrollTopRef.current;
        const currentTop = scrollerEl.scrollTop;
        lastScrollTopRef.current = currentTop;
        const metrics = {
          scrollTop: currentTop,
          scrollHeight: scrollerEl.scrollHeight,
          clientHeight: scrollerEl.clientHeight,
        };
        if (currentTop < previousTop) {
          readyForMoreRef.current = true;
          if (
            shouldPrefetchOlderMessages(
              metrics,
              previousTop,
              HISTORY_PREFETCH_DISTANCE_PX,
            )
          ) {
            loadOlderFromTopRef.current();
          }
        }
      };
      const onWheel = (event: WheelEvent) => {
        if (!shouldTrapEdgeWheel(scrollerEl, event.deltaY)) return;
        if (event.deltaY < 0 && scrollerEl.scrollTop <= 1) {
          readyForMoreRef.current = true;
          loadOlderFromTopRef.current();
        }
        event.preventDefault();
        event.stopPropagation();
      };
      scrollerEl.addEventListener("scroll", onScroll, { passive: true });
      scrollerEl.addEventListener("wheel", onWheel, { passive: false });
      detachScrollerListenersRef.current = () => {
        scrollerEl.removeEventListener("scroll", onScroll);
        scrollerEl.removeEventListener("wheel", onWheel);
      };
    },
    [],
  );

  useEffect(
    () => () => {
      detachScrollerListenersRef.current?.();
      detachScrollerListenersRef.current = null;
      scrollerElRef.current = null;
    },
    [],
  );

  const handleStartReached = useCallback(() => {
    // Ignore the initial mount/snap top-touch and any fire that is not the
    // result of a real upward scroll.
    loadOlderFromTop();
  }, [loadOlderFromTop]);

  const followOutput = useCallback(
    (isAtBottom: boolean) =>
      !isPrependingHistoryRef.current && isAtBottom ? ("auto" as const) : false,
    [],
  );

  // Stable identity for the Virtuoso `itemContent` callback. Without this the
  // inline arrow at the call site rebuilds every render, and Virtuoso re-renders
  // all visible message rows on every keystroke / new message. Deps are the two
  // values read inside (the message list for grouping lookahead, and the
  // firstItemIndex offset that shifts on prepend). Signature matches Virtuoso's
  // native (index, item) order so it can be passed directly as `itemContent`.
  const renderMessage = useCallback(
    (virtuosoIndex: number, m: Message) => {
      const kind = classify(m);
      const pos = virtuosoIndex - firstItemIndex;
      const prevMsg = pos > 0 ? visibleMessages[pos - 1] : null;
      const prevKind = prevMsg ? classify(prevMsg) : null;
      const isGrouped = prevKind === kind;

      return <ChatMessageRow message={m} kind={kind} isGrouped={isGrouped} />;
    },
    [visibleMessages, firstItemIndex],
  );

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reply.trim() || !canHumanReply) return;

    setIsSending(true);
    try {
      await dataProvider.sendHumanReply(conversationId, reply);
      setReply("");
    } catch (err: unknown) {
      const status = err instanceof HumanReplyError ? err.status : "error";
      notify(translate(`resources.conversations.reply.${status}`), {
        type: "error",
      });
    } finally {
      setIsSending(false);
    }
  };

  // Keep the Virtuoso component slots referentially stable except when the
  // loading flags actually change — otherwise typing in the composer would
  // recreate this object every keystroke and force Virtuoso to remount.
  const virtuosoComponents = useMemo(
    () => ({
      List: ChatItemList,
      Header: () => (
        <div className="chat-history-top-spacer">
          {isLoadingMore ? (
            <div
              className="day-marker"
              style={{ margin: "8px 0", background: "transparent" }}
            >
              <span>Đang tải tin nhắn cũ hơn...</span>
            </div>
          ) : null}
        </div>
      ),
      Footer: () => <div className="chat-history-bottom-spacer" />,
      EmptyPlaceholder: () =>
        isLoading ? (
          <div className="day-marker" style={{ background: "transparent" }}>
            <span>Đang tải tin nhắn...</span>
          </div>
        ) : (
          <div className="empty-state">Chưa có tin nhắn nào.</div>
        ),
    }),
    [isLoading, isLoadingMore],
  );

  // Fragment — the host shell lays out the scroll surface (1fr) and composer
  // (auto); the scroll shell only gives us a stable overlay layer.
  return (
    <>
      <div className="chat-scroll-shell">
        <Virtuoso
          ref={virtuosoRef}
          scrollerRef={setScrollerRef}
          className="chat-scroller"
          style={
            {
              height: "100%",
              "--chat-composer-reserve": `${composerReserve}px`,
            } as CSSProperties
          }
          data={visibleMessages}
          computeItemKey={(_, m) => `${m.conversation_id}:${m.id}`}
          firstItemIndex={firstItemIndex}
          startReached={handleStartReached}
          atBottomStateChange={handleAtBottomStateChange}
          atBottomThreshold={CHAT_AT_BOTTOM_THRESHOLD_PX}
          atTopThreshold={CHAT_AT_TOP_THRESHOLD_PX}
          followOutput={followOutput}
          totalListHeightChanged={handleTotalListHeightChanged}
          defaultItemHeight={DEFAULT_CHAT_ITEM_HEIGHT_PX}
          heightEstimates={messageHeightEstimates}
          itemSize={measureMessageItem}
          increaseViewportBy={VIRTUOSO_INCREASE_VIEWPORT_BY}
          minOverscanItemCount={VIRTUOSO_MIN_OVERSCAN_ITEM_COUNT}
          components={virtuosoComponents}
          itemContent={renderMessage}
        />
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

      <footer ref={composerWrapRef} className="composer-wrap">
        {showComposerTakeoverNotice && isBotMode && (
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
        <form
          className={`composer ${!canHumanReply ? "disabled" : ""}`}
          onSubmit={handleSend}
        >
          <textarea
            ref={textareaRef}
            rows={1}
            placeholder={
              canHumanReply
                ? "Nhập tin nhắn..."
                : isBotMode
                  ? "Đang dùng ChatBot"
                  : "Chưa sẵn sàng"
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
      </footer>
    </>
  );
};
