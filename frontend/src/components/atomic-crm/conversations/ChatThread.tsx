import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import { useDataProvider, useNotify, useTranslate } from "ra-core";
import type { Conversation, Message } from "../types";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import { HumanReplyError } from "@/lib/vfic/humanReplyService";
import { useConversationActions } from "./useConversationActions";
import { useConversationRealtime } from "./useConversationRealtime";

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
  const { messages, isLoading, isLoadingMore, hasMore, loadMore } =
    useConversationRealtime(conversationId);
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const translate = useTranslate();
  const [reply, setReply] = useState("");
  const [isSending, setIsSending] = useState(false);
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const [firstItemIndex, setFirstItemIndex] = useState(0);
  const initialJumpDoneRef = useRef(false);
  // Load older messages only on a genuine upward scroll — not merely because
  // the top happens to be visible (which is the case the moment a thread opens,
  // when the initial page fits the viewport, and would otherwise auto-fetch the
  // whole history). Armed by the scroll listener below, disarmed after each
  // page so one scroll-up = one page and the list can never run away.
  const [scrollerEl, setScrollerEl] = useState<HTMLElement | null>(null);
  const readyForMoreRef = useRef(false);

  const {
    isBotMode: internalIsBotMode,
    canHumanReply: internalCanHumanReply,
    handleTakeover: internalHandleTakeover,
  } = useConversationActions(conversation);
  const isBotMode = isBotModeOverride ?? internalIsBotMode;
  const canHumanReply = canHumanReplyOverride ?? internalCanHumanReply;
  const handleTakeover = onTakeoverOverride ?? internalHandleTakeover;

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

  // Snap to the newest message instantly when a conversation opens, then let
  // Virtuoso's followOutput handle subsequent appends (smooth only when the
  // user is already at the bottom — reading history is never yanked away).
  useEffect(() => {
    if (messages.length > 0 && !initialJumpDoneRef.current) {
      initialJumpDoneRef.current = true;
      virtuosoRef.current?.scrollToIndex({
        index: "LAST",
        align: "end",
        behavior: "auto",
      });
    }
  }, [messages]);

  // Reset per-conversation state so each thread opens at its newest message.
  useEffect(() => {
    initialJumpDoneRef.current = false;
    readyForMoreRef.current = false;
    setFirstItemIndex(0);
  }, [conversationId]);

  // Arm "load more" only after the user scrolls away from the bottom (i.e.
  // scrolls up to read history). A freshly opened thread parks at the newest
  // message, so the top being visible there must NOT trigger a fetch.
  useEffect(() => {
    if (!scrollerEl) return;
    const onScroll = () => {
      const atBottom =
        scrollerEl.scrollTop + scrollerEl.clientHeight >=
        scrollerEl.scrollHeight - 1;
      if (!atBottom) readyForMoreRef.current = true;
    };
    scrollerEl.addEventListener("scroll", onScroll, { passive: true });
    return () => scrollerEl.removeEventListener("scroll", onScroll);
  }, [scrollerEl]);

  const handleStartReached = useCallback(() => {
    // Ignore the initial mount/snap top-touch and any fire that is not the
    // result of a real upward scroll.
    if (!initialJumpDoneRef.current) return;
    if (!readyForMoreRef.current) return;
    if (hasMore && messages.length > 0) {
      // Disarm until the next upward scroll — one page per scroll-up.
      readyForMoreRef.current = false;
      loadMore(messages[0].id).then((count: number) => {
        if (count > 0) setFirstItemIndex((i) => i + count);
      });
    }
  }, [hasMore, messages, loadMore]);

  const followOutput = useCallback(
    (isAtBottom: boolean) => (isAtBottom ? ("smooth" as const) : false),
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
          <div className={kind === "system" ? "day-marker" : "system-event"}>
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
        <div className={`message-row ${kind} ${isGrouped ? "grouped" : ""}`}>
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

  // Keep the Virtuoso component slots referentially stable except when the
  // loading flags actually change — otherwise typing in the composer would
  // recreate this object every keystroke and force Virtuoso to remount.
  const virtuosoComponents = useMemo(
    () => ({
      Header: () =>
        isLoadingMore ? (
          <div
            className="day-marker"
            style={{ margin: "8px 0", background: "transparent" }}
          >
            <span>Đang tải tin nhắn cũ hơn...</span>
          </div>
        ) : null,
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
        scrollerRef={(el) => setScrollerEl(el as HTMLElement | null)}
        className="chat-scroller"
        style={{ height: "100%" }}
        data={messages}
        computeItemKey={(_, m) => m.id}
        firstItemIndex={firstItemIndex}
        startReached={handleStartReached}
        followOutput={followOutput}
        components={virtuosoComponents}
        itemContent={renderMessage}
      />

      <footer className="composer-wrap">
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
          className={`composer ${!canHumanReply ? "disabled" : ""}`}
          onSubmit={handleSend}
        >
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
