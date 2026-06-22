import { useEffect, useState, useRef, useMemo } from "react";
import {
  ShowBase,
  useRecordContext,
  useDataProvider,
  useNotify,
  useTranslate,
  useGetList,
} from "ra-core";
import { TopToolbar } from "../layout/TopToolbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AlertTriangle,
  Bot,
  Inbox,
  Lock,
  Send,
  Sparkles,
  UserCircle,
  User as UserIcon,
  Wrench,
} from "lucide-react";
import { getSupabaseClient } from "../providers/supabase/supabase";
import { cn } from "@/lib/utils";
import { LEAD_STAGES } from "../types";
import type { Conversation, Message, Lead } from "../types";
import { CrmDataProvider } from "../providers/supabase/dataProvider";
import { HumanReplyError } from "@/lib/vfic/humanReplyService";
import { useConversationActions } from "./useConversationActions";

type SenderKind = "candidate" | "bot" | "recruiter" | "system" | "tool";

const stageLabel = (value: string) =>
  LEAD_STAGES.find((s) => s.value === value)?.label ?? value;

const classify = (msg: Message): SenderKind => {
  // Tool calls (RAG lookups, lead ops) are flagged on the mapped message via
  // data.tool by toMessage(); they render as muted, centered bubbles.
  if (msg.data?.tool) return "tool";
  if (msg.type === "system") return "system";
  if (msg.type === "inbound") return "candidate";
  if (msg.data?.recruiter_id) return "recruiter";
  return "bot";
};

const SENDER_META: Record<
  SenderKind,
  {
    label: string;
    icon: typeof Bot;
    bubble: string;
    align: "start" | "end" | "center";
    avatar?: string;
  }
> = {
  candidate: {
    label: "Ứng viên",
    icon: UserIcon,
    bubble: "bg-card border border-border/50 text-card-foreground shadow-sm rounded-2xl rounded-tr-sm",
    align: "end",
    avatar: "bg-primary text-primary-foreground",
  },
  bot: {
    label: "AI Bot",
    icon: Bot,
    bubble: "bg-primary/10 border border-primary/20 text-foreground shadow-sm rounded-2xl rounded-tl-sm",
    align: "start",
    avatar: "bg-primary/20 text-primary border border-primary/30",
  },
  recruiter: {
    label: "Nhân viên",
    icon: UserCircle,
    bubble: "bg-primary text-primary-foreground shadow-sm rounded-2xl rounded-tl-sm",
    align: "start",
    avatar: "bg-primary text-primary-foreground",
  },
  system: {
    label: "Hệ thống",
    icon: Sparkles,
    bubble:
      "bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-100 rounded-full",
    align: "center",
  },
  tool: {
    label: "Công cụ",
    icon: Wrench,
    bubble:
      "border border-dashed border-border bg-muted/60 text-muted-foreground rounded-xl",
    align: "center",
  },
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

const extractText = (value: unknown): string => {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value
      .map((part) =>
        part && typeof part === "object" && "text" in part
          ? String((part as { text: unknown }).text ?? "")
          : String(part),
      )
      .join("")
      .trim();
  }
  return String(value);
};

/**
 * vfic_chat_histories.message is { type: "ai"|"human"|"tool", content, data? }.
 * Direction cannot come from type alone: candidate-inbound AND recruiter-outbound
 * are both "human". Discriminator = message.data.recruiter_id (set by the n8n
 * "VFIC Human Reply" workflow on recruiter replies).
 */
const toMessage = (row: any): Message | null => {
  const msg = row?.message ?? {};
  const type = String(msg.type ?? "").toLowerCase();
  // ai = bot outbound; human = candidate-inbound OR recruiter-outbound;
  if (type !== "ai" && type !== "human") return null;
  const recruiterId = msg.data?.recruiter_id;
  const isRecruiter = type === "human" && Boolean(recruiterId);
  const rawContent = isRecruiter
    ? (msg.data?.content ?? msg.content)
    : msg.content;
  const content = extractText(rawContent);
  // Filter out internal agent tool calling logs
  if (
    type === "ai" &&
    content.startsWith("Calling ") &&
    content.includes("with input:")
  ) {
    return null;
  }
  const messageType: Message["type"] =
    type === "ai" || isRecruiter ? "outbound" : "inbound";
  return {
    id: String(row.id),
    zalo_message_id: String(row.id),
    conversation_id: row.session_id,
    type: messageType,
    content: content,
    data: { recruiter_id: recruiterId },
    created_at:
      msg.data?.created_at ?? row.created_at ?? new Date().toISOString(),
  };
};

const tryLoadDemoMessages = async (zaloChatId: string): Promise<Message[]> => {
  // Demo data is for local dev only. In production we never want a Supabase
  // outage / RLS denial to silently render fake conversations as real, so the
  // demo loader is a no-op outside dev.
  if (!import.meta.env.DEV) return [];
  try {
    const fakerest = await import("../providers/fakerest");
    const { dataProvider } = fakerest;
    const { data: convs } = await dataProvider.getList("conversations", {
      filter: { zalo_chat_id: zaloChatId },
      pagination: { page: 1, perPage: 1 },
    });
    const convId = (convs?.[0] as any)?.id;
    if (!convId) return [];
    const { data } = await dataProvider.getList("messages", {
      filter: { conversation_id: convId },
      pagination: { page: 1, perPage: 1000 },
      sort: { field: "created_at", order: "ASC" },
    });
    return Array.isArray(data) ? (data as Message[]) : [];
  } catch {
    return [];
  }
};

const useConversationRealtime = (zaloChatId?: string) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!zaloChatId) {
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    setError(null);

    const fetchInitial = async () => {
      try {
        const { data, error: err } = await getSupabaseClient()
          .from("vfic_chat_histories")
          .select("*")
          .eq("session_id", zaloChatId)
          .order("id", { ascending: true });
        if (cancelled) return;
        if (err) {
          // Supabase error: demo data in dev, explicit error UI in production.
          if (import.meta.env.DEV) {
            const demo = await tryLoadDemoMessages(zaloChatId);
            if (cancelled) return;
            setMessages(demo);
          } else {
            setError("Không thể tải cuộc trò chuyện. Vui lòng thử lại.");
            setMessages([]);
          }
          setIsLoading(false);
          return;
        }
        const mapped = (data ?? [])
          .map(toMessage)
          .filter((m): m is Message => m != null);
        setMessages(mapped);
        setIsLoading(false);
      } catch {
        // No Supabase at all: demo data in dev, explicit error UI in production.
        if (cancelled) return;
        if (import.meta.env.DEV) {
          const demo = await tryLoadDemoMessages(zaloChatId);
          if (cancelled) return;
          setMessages(demo);
        } else {
          setError("Could not load the conversation. Please try again.");
          setMessages([]);
        }
        setIsLoading(false);
      }
    };
    fetchInitial();

    let cleanup: (() => void) | undefined;
    try {
      const channel = getSupabaseClient()
        .channel(`chat_${zaloChatId}`)
        .on(
          "postgres_changes",
          {
            event: "INSERT",
            schema: "public",
            table: "vfic_chat_histories",
            filter: `session_id=eq.${zaloChatId}`,
          },
          (payload) => {
            const newMsg = toMessage(payload.new);
            if (!newMsg) return;
            setMessages((prev) =>
              prev.some((m) => m.id === newMsg.id) ? prev : [...prev, newMsg],
            );
          },
        )
        .subscribe();
      cleanup = () => getSupabaseClient().removeChannel(channel);
    } catch {
      // Supabase not available in demo — skip realtime.
    }

    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [zaloChatId]);

  return { messages, isLoading, error };
};

const MessageBubble = ({
  msg,
  showTime,
}: {
  msg: Message;
  showTime?: boolean;
}) => {
  const kind = classify(msg);
  const meta = SENDER_META[kind];
  const Icon = meta.icon;
  const isCentered: boolean = meta.align === "center";

  if (isCentered) {
    return (
      <div className="flex justify-center my-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
        <div
          className={cn(
            "max-w-md px-4 py-1.5 text-center text-xs shadow-sm",
            meta.bubble,
          )}
        >
          <div className="flex items-center justify-center gap-1 font-semibold opacity-80">
            <Icon className="size-3.5" />
            <span>{msg.content}</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex w-full gap-3 animate-in fade-in slide-in-from-bottom-2 duration-300",
        (meta.align as string) === "end" ? "flex-row-reverse" : "flex-row",
      )}
    >
      <div className={cn("w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1 shadow-sm text-sm font-medium", meta.avatar)}>
        <Icon className="size-4" />
      </div>
      <div className="max-w-[75%]">
        <div className={cn("flex items-center gap-2 mb-1.5 mx-1", meta.align === "end" ? "justify-end" : "")}>
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{meta.label}</span>
            {showTime && msg.created_at && (
                <span className="text-xs text-muted-foreground/70">· {formatTime(msg.created_at)}</span>
            )}
        </div>
        <div
          className={cn(
            "px-4 py-3 leading-relaxed text-[15px]",
            meta.bubble,
          )}
        >
          <div className="whitespace-pre-wrap break-words">
            {msg.content}
          </div>
        </div>
      </div>
    </div>
  );
};

export const ConversationShowContent = () => {
  const record = useRecordContext<Conversation>();
  const { messages, isLoading, error } = useConversationRealtime(
    record?.zalo_chat_id,
  );
  const dataProvider = useDataProvider<CrmDataProvider>();
  const notify = useNotify();
  const translate = useTranslate();
  const [reply, setReply] = useState("");
  const [isSending, setIsSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Shared takeover/release logic — the same hook the lead-profile drawer uses,
  // so both action surfaces stay behaviourally identical.
  const { isBotMode, handleTakeover, handleRelease } =
    useConversationActions(record);

  const { data: leadData } = useGetList(
    "leads",
    {
      filter: { zalo_id: record?.zalo_chat_id },
      pagination: { page: 1, perPage: 1 },
    },
    { enabled: !!record?.zalo_chat_id },
  );
  const lead = leadData?.[0] as Lead | undefined;

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const grouped = useMemo(() => {
    const result: Array<{
      msg: Message;
      isFirstOfGroup: boolean;
      isInternalGroup?: boolean;
      groupMessages?: Message[];
    }> = [];
    let currentInternalGroup: Message[] | null = null;

    for (const msg of messages) {
      const kind = classify(msg);
      if (kind === "tool" || kind === "system") {
        if (!currentInternalGroup) {
          currentInternalGroup = [msg];
          result.push({
            msg,
            isFirstOfGroup: true,
            isInternalGroup: true,
            groupMessages: currentInternalGroup,
          });
        } else {
          currentInternalGroup.push(msg);
        }
      } else {
        currentInternalGroup = null;
        const prev = result[result.length - 1];
        const sameKind =
          prev && !prev.isInternalGroup && classify(prev.msg) === kind;
        result.push({ msg, isFirstOfGroup: !sameKind });
      }
    }
    return result;
  }, [messages]);

  if (!record) return null;

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reply.trim() || isBotMode) return;

    setIsSending(true);
    try {
      await dataProvider.sendHumanReply(record.zalo_chat_id, reply);
      setReply(""); // clear only on success — keep the text on failure for retry
    } catch (e: unknown) {
      const status = e instanceof HumanReplyError ? e.status : "error";
      notify(translate(`resources.conversations.reply.${status}`), {
        type: "error",
      });
    } finally {
      setIsSending(false);
    }
  };

  return (
    <Card className="flex h-[calc(100vh-220px)] flex-col overflow-hidden rounded-none border-none shadow-none bg-transparent">
      <CardHeader className="flex flex-row items-center justify-between gap-2 border-b border-border/40 bg-card/80 backdrop-blur-md px-6 py-4 z-20 shrink-0 shadow-sm h-[72px]">
        <div className="flex min-w-0 items-center gap-3">
          <div className="bg-muted p-2 rounded-lg text-muted-foreground hidden sm:block">
            <UserIcon className="size-5" />
          </div>
          <div>
            <CardTitle className="flex items-center gap-2 truncate text-lg font-semibold text-foreground">
              <span className="truncate">
                {lead?.name ||
                  `Khách hàng chưa biết · đuôi ${(record.zalo_chat_id || "").slice(-4)}`}
              </span>
              {lead && (
                <span className="text-sm font-normal text-muted-foreground hidden sm:inline-block">
                  · {lead.desired_job || "Chưa có công việc"}
                </span>
              )}
            </CardTitle>
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mt-0.5">
              <span className={cn("flex items-center gap-1 px-2 py-0.5 rounded border", isBotMode ? "bg-muted/50 border-border" : "bg-primary/10 text-primary border-primary/20")}>
                {isBotMode ? (
                  <>
                    <Bot className="size-3.5" /> Bot đang xử lý
                  </>
                ) : (
                  <>
                    <UserCircle className="size-3.5" /> Nhân viên tiếp nhận
                  </>
                )}
              </span>
              {lead?.lead_stage && (
                <span className="hidden sm:inline-block">· {stageLabel(lead.lead_stage)}</span>
              )}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          {isBotMode ? (
            <Button size="default" onClick={handleTakeover} className="gap-2 rounded-xl font-medium shadow-[0_0_15px_rgba(224,112,31,0.3)] hover:shadow-[0_0_20px_rgba(224,112,31,0.4)] transition-all hover:-translate-y-0.5">
              <UserCircle className="size-4" />
              Tiếp nhận
            </Button>
          ) : (
            <Button
              size="default"
              variant="outline"
              onClick={handleRelease}
              className="gap-2 rounded-xl font-medium bg-background"
            >
              <Bot className="size-4" />
              Trả lại Bot
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col overflow-hidden p-0">
        {error ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <div className="flex max-w-sm flex-col items-center gap-2 text-center">
              <AlertTriangle className="size-8 text-destructive" />
              <p className="font-medium">Không thể tải tin nhắn</p>
              <p className="text-xs text-muted-foreground">{error}</p>
            </div>
          </div>
        ) : isLoading ? (
          <div className="flex flex-1 flex-col gap-3 overflow-hidden p-6">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className={cn(
                  "flex w-full",
                  i % 2 === 0 ? "justify-start" : "justify-end",
                )}
              >
                <Skeleton
                  className={cn(
                    "h-14 rounded-2xl",
                    i % 2 === 0 ? "w-2/5" : "w-1/2",
                  )}
                />
              </div>
            ))}
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <div className="flex flex-col items-center gap-3 text-center">
              <div className="rounded-full bg-muted p-4">
                <Inbox className="size-8 text-muted-foreground" />
              </div>
              <div>
                <p className="font-medium">Chưa có tin nhắn</p>
                <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                  Lịch sử trò chuyện trống. Tin nhắn mới từ Zalo sẽ hiển thị tại
                  đây theo thời gian thực.
                </p>
              </div>
            </div>
          </div>
        ) : (
          <div
            className="flex-1 overflow-y-auto px-4 py-6 md:px-6 z-10"
            ref={scrollRef}
          >
            <div className="flex flex-col gap-6">
              {grouped.map(
                ({ msg, isFirstOfGroup, isInternalGroup, groupMessages }) => {
                  if (isInternalGroup && groupMessages) {
                    return (
                      <details key={msg.id} className="w-full my-2 text-center fade-in-up">
                        <summary className="cursor-pointer inline-flex items-center gap-1.5 px-3 py-1 rounded-full border border-border bg-card shadow-sm text-xs text-muted-foreground select-none opacity-80 hover:opacity-100 list-none outline-none transition-opacity">
                          <Sparkles className="size-3" />
                          Hoạt động AI · {groupMessages.length} hành động
                        </summary>
                        <div className="w-full mt-4 flex flex-col gap-3">
                          {groupMessages.map((m, i) => (
                            <MessageBubble
                              key={m.id}
                              msg={m}
                              showTime={i === 0}
                            />
                          ))}
                        </div>
                      </details>
                    );
                  }
                  return (
                    <MessageBubble
                      key={msg.id}
                      msg={msg}
                      showTime={isFirstOfGroup}
                    />
                  );
                },
              )}
            </div>
            <div className="h-8"></div>
          </div>
        )}

        <div className="border-t border-border/40 bg-card p-4 shrink-0 relative z-20">
          {isBotMode ? (
            <div className="bg-muted/80 backdrop-blur border border-border/50 rounded-xl p-3 mb-4 flex items-start gap-3 shadow-sm">
              <Lock className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <div>
                <p className="text-sm text-foreground font-medium">Bot đang xử lý cuộc trò chuyện này. Hãy tiếp nhận để bắt đầu trả lời thủ công.</p>
              </div>
            </div>
          ) : null}
          <form onSubmit={handleSend} className="flex items-center gap-3">
            <div className="flex-1 relative">
              <input
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                placeholder={
                  isBotMode
                    ? "Hãy tiếp nhận cuộc trò chuyện để trả lời..."
                    : "Nhập câu trả lời..."
                }
                disabled={isBotMode || isSending}
                className={cn(
                  "w-full bg-muted/50 border border-border/50 text-foreground text-sm rounded-xl py-3 px-4 outline-none transition-all placeholder:text-muted-foreground",
                  !isBotMode && "focus:ring-2 focus:ring-primary/20 focus:bg-background focus:border-primary/30",
                  isBotMode && "cursor-not-allowed opacity-70"
                )}
                autoComplete="off"
              />
            </div>
            <button
              type="submit"
              disabled={isBotMode || isSending || !reply.trim()}
              aria-label="Gửi tin nhắn"
              title="Gửi tin nhắn"
              className={cn(
                "w-11 h-11 rounded-xl flex items-center justify-center transition-colors shadow-sm",
                isBotMode || isSending || !reply.trim()
                  ? "bg-muted text-muted-foreground cursor-not-allowed"
                  : "bg-primary text-primary-foreground hover:bg-primary/90"
              )}
            >
              <Send className="size-5" />
            </button>
          </form>
        </div>
      </CardContent>
    </Card>
  );
};

export const ConversationShow = () => {
  return (
    <ShowBase>
      <TopToolbar>
        <h2 className="mr-auto text-xl font-semibold">Cuộc trò chuyện</h2>
      </TopToolbar>
      <ConversationShowContent />
    </ShowBase>
  );
};
