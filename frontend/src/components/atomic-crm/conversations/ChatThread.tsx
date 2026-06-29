import {
  forwardRef,
  useEffect,
  useLayoutEffect,
  useState,
  useRef,
  useCallback,
  useMemo,
  type CSSProperties,
  type HTMLAttributes,
} from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import { useDataProvider, useNotify, useTranslate } from "ra-core";
import type { Conversation, Message } from "../types";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import { HumanReplyError } from "@/lib/vfic/humanReplyService";
import { useConversationActions } from "./useConversationActions";
import { useConversationRealtime } from "./useConversationRealtime";
import { shouldTrapEdgeWheel } from "./chatEdgeScroll";

// ChatThread is the reusable, shell-agnostic message thread + composer. It owns
// the realtime subscription, the virtualised scroller (with all the snap /
// load-more arming logic), the reply composer and the bot→human takeover
// affordance. It renders a FRAGMENT (<Virtuoso/> + <footer/>) so the host shell
// lays out the scroller (1fr) and composer (auto) — the inbox center-panel grid
// and the lead-page .chat-surface grid both do this. Styling comes from the
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

const QUICK_EMOJIS = [
  "😊",
  "👍",
  "🙏",
  "❤️",
  "🎉",
  "✅",
  "💼",
  "📍",
  "📞",
  "🚌",
  "🏠",
  "💰",
  "⏰",
  "📄",
  "✨",
  "🙌",
];
const COMPOSER_TEXTAREA_MAX_HEIGHT = 120;
const DEFAULT_COMPOSER_RESERVE_PX = 104;
const COMPOSER_RESERVE_GAP_PX = 16;
const DEFAULT_CHAT_ITEM_HEIGHT_PX = 96;
const ANCHOR_RESTORE_FRAMES = 6;

type ScrollAnchor = {
  id: string;
  offsetTop: number;
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
  const [emojiOpen, setEmojiOpen] = useState(false);
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composerRef = useRef<HTMLFormElement>(null);
  const composerWrapRef = useRef<HTMLElement>(null);
  const emojiPickerRef = useRef<HTMLDivElement>(null);
  const scrollerElRef = useRef<HTMLElement | null>(null);
  const detachScrollerListenersRef = useRef<(() => void) | null>(null);
  const initialJumpDoneRef = useRef(false);
  const initialBottomSettleUntilRef = useRef(0);
  const initialBottomSettleRafRef = useRef<number | null>(null);
  const lastScrollTopRef = useRef(0);
  const lastLoadMoreAtRef = useRef(0);
  const [composerReserve, setComposerReserve] = useState(
    DEFAULT_COMPOSER_RESERVE_PX,
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

  const scrollToNewest = useCallback(() => {
    virtuosoRef.current?.scrollToIndex({
      index: "LAST",
      align: "end",
      behavior: "auto",
    });
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
    lastScrollTopRef.current = 0;
    lastLoadMoreAtRef.current = 0;
    setEmojiOpen(false);
  }, [conversationId]);

  // Snap to the newest message instantly when a conversation opens, then let
  // Virtuoso's followOutput handle subsequent appends only when the user is
  // already at the bottom. Very tall bubbles can be measured after the first
  // snap, so totalListHeightChanged keeps the initial open pinned briefly.
  useEffect(() => {
    if (messages.length > 0 && !initialJumpDoneRef.current) {
      initialJumpDoneRef.current = true;
      initialBottomSettleUntilRef.current = performance.now() + 800;
      scrollToNewest();
      scheduleScrollToNewest();
    }
  }, [messages, scheduleScrollToNewest, scrollToNewest]);

  const handleTotalListHeightChanged = useCallback(() => {
    if (!initialJumpDoneRef.current) return;
    if (performance.now() > initialBottomSettleUntilRef.current) return;
    if (readyForMoreRef.current) return;
    scheduleScrollToNewest();
  }, [scheduleScrollToNewest]);

  const findMessageElement = useCallback(
    (scrollerEl: HTMLElement, messageId: string) =>
      Array.from(
        scrollerEl.querySelectorAll<HTMLElement>("[data-message-id]"),
      ).find((el) => el.dataset.messageId === messageId) ?? null,
    [],
  );

  const captureScrollAnchor = useCallback((): ScrollAnchor | null => {
    const scrollerEl = scrollerElRef.current;
    if (!scrollerEl) return null;

    const scrollerTop = scrollerEl.getBoundingClientRect().top;
    const anchorEl =
      Array.from(
        scrollerEl.querySelectorAll<HTMLElement>("[data-message-id]"),
      ).find((el) => el.getBoundingClientRect().bottom > scrollerTop + 1) ??
      null;
    const id = anchorEl?.dataset.messageId;
    if (!anchorEl || !id) return null;

    return {
      id,
      offsetTop: anchorEl.getBoundingClientRect().top - scrollerTop,
    };
  }, []);

  const restoreScrollAnchor = useCallback(
    (anchor: ScrollAnchor | null) => {
      if (!anchor) return;

      let frame = 0;
      const tick = () => {
        const scrollerEl = scrollerElRef.current;
        if (!scrollerEl) return;

        const anchorEl = findMessageElement(scrollerEl, anchor.id);
        if (anchorEl) {
          const currentOffset =
            anchorEl.getBoundingClientRect().top -
            scrollerEl.getBoundingClientRect().top;
          const delta = currentOffset - anchor.offsetTop;
          if (Math.abs(delta) > 0.5) {
            scrollerEl.scrollTop += delta;
            lastScrollTopRef.current = scrollerEl.scrollTop;
          }
        }

        frame += 1;
        if (frame < ANCHOR_RESTORE_FRAMES) {
          requestAnimationFrame(tick);
        }
      };

      requestAnimationFrame(tick);
    },
    [findMessageElement],
  );

  const loadOlderFromTop = useCallback(() => {
    if (!initialJumpDoneRef.current) return;
    if (!readyForMoreRef.current) return;
    if (isLoadingMore) return;
    if (!hasMore || messages.length === 0) return;

    const now = performance.now();
    if (now - lastLoadMoreAtRef.current < 350) return;
    lastLoadMoreAtRef.current = now;

    const anchor = captureScrollAnchor();
    const anchorDataIndex = anchor
      ? messages.findIndex((msg) => msg.id === anchor.id)
      : -1;
    const anchorVirtuosoIndex =
      anchorDataIndex >= 0 ? firstItemIndex + anchorDataIndex : null;
    readyForMoreRef.current = false;
    void loadMore(messages[0].id).then((added) => {
      if (added <= 0) return;
      if (anchorVirtuosoIndex !== null) {
        virtuosoRef.current?.scrollToIndex({
          index: anchorVirtuosoIndex,
          align: "start",
          behavior: "auto",
        });
      }
      restoreScrollAnchor(anchor);
    });
  }, [
    hasMore,
    isLoadingMore,
    messages,
    firstItemIndex,
    loadMore,
    captureScrollAnchor,
    restoreScrollAnchor,
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

  useEffect(() => {
    if (!emojiOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (composerRef.current?.contains(target)) return;
      if (emojiPickerRef.current?.contains(target)) return;
      setEmojiOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [emojiOpen]);

  // Arm "load more" only after the user scrolls away from the bottom (i.e.
  // scrolls up to read history). A freshly opened thread parks at the newest
  // message, so the top being visible there must NOT trigger a fetch.
  const setScrollerRef = useCallback((el: HTMLElement | Window | null) => {
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
      const atBottom =
        currentTop + scrollerEl.clientHeight >= scrollerEl.scrollHeight - 1;
      if (atBottom) {
        readyForMoreRef.current = false;
        return;
      }
      if (currentTop < previousTop) {
        readyForMoreRef.current = true;
        if (currentTop <= 1) loadOlderFromTopRef.current();
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
  }, []);

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
    (isAtBottom: boolean) => (isAtBottom ? ("auto" as const) : false),
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
      if (kind === "system" || kind === "event") {
        return (
          <div
            className={kind === "system" ? "day-marker" : "system-event"}
            data-message-id={m.id}
          >
            {kind === "event" && (
              <svg className="icon">
                <use href="#i-sparkles" />
              </svg>
            )}
            <span>{m.content}</span>
          </div>
        );
      }

      const pos = virtuosoIndex - firstItemIndex;
      const prevMsg = pos > 0 ? messages[pos - 1] : null;
      const prevKind = prevMsg ? classify(prevMsg) : null;
      const isGrouped = prevKind === kind;
      const avatarIcon = kind === "bot" ? "i-bot" : "i-user";

      return (
        <div
          className={`message-row ${kind} ${isGrouped ? "grouped" : ""}`}
          data-message-id={m.id}
        >
          {kind === "user" && !isGrouped ? (
            <span className="message-avatar">
              <svg className="icon">
                <use href={`#${avatarIcon}`} />
              </svg>
            </span>
          ) : kind === "user" && isGrouped ? (
            <span
              className="message-avatar-placeholder"
              style={{ width: 32 }}
            />
          ) : null}
          <div className="bubble">
            <div className="bubble-content">
              <p>{m.content}</p>
              <span className="bubble-time-inline">
                {formatTime(m.created_at)}
              </span>
            </div>
          </div>
          {kind !== "user" && !isGrouped ? (
            <span className="message-avatar">
              <svg className="icon">
                <use href={`#${avatarIcon}`} />
              </svg>
            </span>
          ) : kind !== "user" && isGrouped ? (
            <span
              className="message-avatar-placeholder"
              style={{ width: 32 }}
            />
          ) : null}
        </div>
      );
    },
    [messages, firstItemIndex],
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

  const insertEmoji = (emoji: string) => {
    const textarea = textareaRef.current;
    const start = textarea?.selectionStart ?? reply.length;
    const end = textarea?.selectionEnd ?? reply.length;
    const next = `${reply.slice(0, start)}${emoji}${reply.slice(end)}`;
    setReply(next);
    requestAnimationFrame(() => {
      textarea?.focus();
      const cursor = start + emoji.length;
      textarea?.setSelectionRange(cursor, cursor);
    });
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

  // Fragment — the host shell lays out the scroller (1fr) and composer (auto).
  return (
    <>
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
        data={messages}
        computeItemKey={(_, m) => m.id}
        firstItemIndex={firstItemIndex}
        startReached={handleStartReached}
        followOutput={followOutput}
        totalListHeightChanged={handleTotalListHeightChanged}
        defaultItemHeight={DEFAULT_CHAT_ITEM_HEIGHT_PX}
        components={virtuosoComponents}
        itemContent={renderMessage}
      />

      <footer ref={composerWrapRef} className="composer-wrap">
        {showComposerTakeoverNotice && isBotMode && (
          <div className="handoff-note">
            <svg className="icon">
              <use href="#i-bot" />
            </svg>
            <span>AI đang trả lời cuộc trò chuyện này.</span>
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
          ref={composerRef}
          className={`composer ${!canHumanReply ? "disabled" : ""}`}
          onSubmit={handleSend}
        >
          {emojiOpen && (
            <div
              ref={emojiPickerRef}
              className="emoji-picker"
              role="menu"
              aria-label="Chọn biểu tượng cảm xúc"
            >
              {QUICK_EMOJIS.map((emoji) => (
                <button
                  key={emoji}
                  type="button"
                  className="emoji-option"
                  onClick={() => insertEmoji(emoji)}
                  aria-label={`Chèn ${emoji}`}
                >
                  {emoji}
                </button>
              ))}
            </div>
          )}
          <button
            type="button"
            className="composer-action"
            aria-label="Đính kèm"
            disabled={!canHumanReply}
          >
            <svg className="icon">
              <use href="#i-paperclip" />
            </svg>
          </button>
          <textarea
            ref={textareaRef}
            rows={1}
            placeholder={
              canHumanReply
                ? "Nhập tin nhắn..."
                : isBotMode
                  ? "Chuyển sang Manual hoặc Semi auto để trả lời..."
                  : "Hội thoại chưa sẵn sàng để trả lời..."
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
            type="button"
            className="composer-action"
            aria-label="Biểu tượng cảm xúc"
            disabled={!canHumanReply}
            aria-expanded={emojiOpen}
            onClick={() => setEmojiOpen((open) => !open)}
          >
            <svg className="icon">
              <use href="#i-smile" />
            </svg>
          </button>
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
