import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import {
  useRecordContext,
  useDataProvider,
  useNotify,
  useTranslate,
  useGetList,
  ShowBase,
} from "ra-core";
import type { Conversation, Message, Lead } from "../types";
import { CrmDataProvider } from "../providers/supabase/dataProvider";
import { HumanReplyError } from "@/lib/vfic/humanReplyService";
import { useConversationActions } from "./useConversationActions";
import { getLeadStatusColor } from "./ConversationList";
import { chatRepository } from "./chatRepository";
import { LeadProfilePanel } from "../leads/LeadProfilePanel";

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

const tryLoadDemoMessages = async (
  zaloChatId: string,
  options?: { limit?: number; beforeId?: string },
): Promise<{ messages: Message[]; hasMore: boolean }> => {
  if (!import.meta.env.DEV) return { messages: [], hasMore: false };
  try {
    const fakerest = await import("../providers/fakerest");
    const { dataProvider } = fakerest;
    const { data: convs } = await dataProvider.getList("conversations", {
      filter: { zalo_chat_id: zaloChatId },
      pagination: { page: 1, perPage: 1 },
    });
    const convId = (convs?.[0] as any)?.id;
    if (!convId) return { messages: [], hasMore: false };
    const { data } = await dataProvider.getList("messages", {
      filter: { conversation_id: convId },
      pagination: { page: 1, perPage: 1000 },
      sort: { field: "created_at", order: "DESC" },
    });
    let list = Array.isArray(data) ? (data as Message[]) : [];
    if (options?.beforeId) {
      const idx = list.findIndex((m) => String(m.id) === options.beforeId);
      if (idx !== -1) {
        list = list.slice(idx + 1);
      }
    }
    const rawCount = list.length;
    const limit = options?.limit ?? 10;
    const hasMore = rawCount > limit;
    if (options?.limit) {
      list = list.slice(0, options.limit);
    }
    return {
      messages: list.reverse(),
      hasMore,
    };
  } catch {
    return { messages: [], hasMore: false };
  }
};

const useConversationRealtime = (zaloChatId?: string) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const isFetchingRef = useRef(false);

  const fetchInitial = async () => {
    if (!zaloChatId) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    try {
      const { messages: mapped, hasMore: apiHasMore } =
        await chatRepository.getConversationMessages(zaloChatId, {
          limit: 10,
        });
      // Merge, don't replace: a realtime INSERT between subscribe() and this
      // resolve is already in state, and a blind setMessages(mapped) would
      // drop it (the fetch predates the insert). Union by id, fetched-first.
      setMessages((prev) => {
        if (prev.length === 0) return mapped;
        const fetchedIds = new Set(mapped.map((m) => m.id));
        const realtimeOnly = prev.filter((m) => !fetchedIds.has(m.id));
        return realtimeOnly.length > 0 ? [...mapped, ...realtimeOnly] : mapped;
      });
      setHasMore(apiHasMore);
    } catch {
      if (import.meta.env.DEV) {
        const { messages: demo, hasMore: demoHasMore } =
          await tryLoadDemoMessages(zaloChatId, { limit: 10 });
        setMessages(demo);
        setHasMore(demoHasMore);
      } else {
        setMessages([]);
        setHasMore(false);
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    setMessages([]);
    setHasMore(false);
    fetchInitial();

    if (!zaloChatId) return;

    let cleanup: (() => void) | undefined;
    try {
      cleanup = chatRepository.subscribeToMessages(zaloChatId, (newMsg) => {
        setMessages((prev) =>
          prev.some((m) => m.id === newMsg.id) ? prev : [...prev, newMsg],
        );
      });
    } catch {}

    return () => {
      cleanup?.();
    };
  }, [zaloChatId]);

  // Stable identity so the consumer's useCallback(handleStartReached) memo
  // holds across renders — without this the startReached handler is rebuilt
  // every keystroke and Virtuoso re-binds the scroll listener.
  const loadMore = useCallback(
    async (earliestId: string): Promise<number> => {
      if (isFetchingRef.current || !hasMore || !zaloChatId) {
        return 0;
      }
      isFetchingRef.current = true;
      setIsLoadingMore(true);

      try {
        const { messages: older, hasMore: apiHasMore } =
          await chatRepository.getConversationMessages(zaloChatId, {
            limit: 10,
            beforeId: earliestId,
          });
        setHasMore(apiHasMore);
        setMessages((prev) => [...older, ...prev]);
        return older.length;
      } catch {
        if (import.meta.env.DEV) {
          const { messages: demo, hasMore: demoHasMore } =
            await tryLoadDemoMessages(zaloChatId, {
              limit: 10,
              beforeId: earliestId,
            });
          setHasMore(demoHasMore);
          setMessages((prev) => [...demo, ...prev]);
          return demo.length;
        }
        // A failed load-more must not keep re-firing on every scroll-to-top
        // (hasMore stays true -> the backend gets spammed with failing
        // requests). Stop the loop; reopening the conversation retries.
        setHasMore(false);
        return 0;
      } finally {
        setIsLoadingMore(false);
        isFetchingRef.current = false;
      }
    },
    [hasMore, zaloChatId],
  );

  return { messages, isLoading, isLoadingMore, hasMore, loadMore };
};

export const ConversationShowContent = ({
  onOpenList,
}: {
  onOpenList?: () => void;
}) => {
  const record = useRecordContext<Conversation>();
  const { messages, isLoading, isLoadingMore, hasMore, loadMore } =
    useConversationRealtime(record?.zalo_chat_id);
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const translate = useTranslate();
  const [reply, setReply] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
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

  const { isBotMode, handleTakeover } = useConversationActions(record);

  // Server-confirm the optimistic unread clear from the inbox list. Skips the
  // round-trip when nothing is unread, and re-fires if a realtime inbound bumps
  // the counter while the recruiter is viewing the thread. vfic_mark_read resets
  // unread_count without touching updated_at (no inbox re-sort).
  useEffect(() => {
    if (!record?.zalo_chat_id) return;
    if ((record.unread_count ?? 0) === 0) return;
    dataProvider.markAsRead(record.zalo_chat_id).catch(() => {
      /* non-fatal: badge re-syncs on the next list load */
    });
  }, [record?.zalo_chat_id, record?.unread_count, dataProvider]);

  const { data: leadData } = useGetList(
    "leads",
    {
      filter: { zalo_id: record?.zalo_chat_id },
      pagination: { page: 1, perPage: 1 },
    },
    { enabled: !!record?.zalo_chat_id },
  );
  const lead = leadData?.[0] as Lead | undefined;

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
  }, [record?.zalo_chat_id]);

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
            <span className="message-avatar-placeholder" style={{ width: 32 }} />
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
            <span className="message-avatar-placeholder" style={{ width: 32 }} />
          ) : null}
        </div>
      );
    },
    [messages, firstItemIndex],
  );

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reply.trim() || isBotMode) return;

    setIsSending(true);
    try {
      await dataProvider.sendHumanReply(record!.zalo_chat_id, reply);
      setReply("");
    } catch (e: unknown) {
      const status = e instanceof HumanReplyError ? e.status : "error";
      notify(translate(`resources.conversations.reply.${status}`), {
        type: "error",
      });
    } finally {
      setIsSending(false);
    }
  };

  const name =
    lead?.name || `Ứng viên · ${(record?.zalo_chat_id || "").slice(-4)}`;
  const colors = getLeadStatusColor(lead);

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
              backgroundImage: "none",
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
          </div>
        </div>
        <div className="header-actions">
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
        <div className="handoff-note">
          {isBotMode && (
            <>
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
            </>
          )}
        </div>
        <form
          className={`composer ${isBotMode ? "disabled" : ""}`}
          onSubmit={handleSend}
        >
          <button
            type="button"
            className="composer-action"
            aria-label="Đính kèm"
            disabled={isBotMode}
          >
            <svg className="icon">
              <use href="#i-paperclip" />
            </svg>
          </button>
          <textarea
            rows={1}
            placeholder={
              isBotMode
                ? "Tiếp nhận cuộc trò chuyện để trả lời…"
                : "Nhập tin nhắn..."
            }
            disabled={isBotMode || isSending}
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
            disabled={isBotMode}
          >
            <svg className="icon">
              <use href="#i-smile" />
            </svg>
          </button>
          <button
            type="submit"
            className="composer-action send"
            aria-label="Gửi tin nhắn"
            disabled={isBotMode || isSending || !reply.trim()}
          >
            <svg className="icon">
              <use href="#i-send" />
            </svg>
          </button>
        </form>
      </footer>

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
