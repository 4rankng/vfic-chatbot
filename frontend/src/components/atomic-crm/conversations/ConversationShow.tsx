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
import type { Conversation, Message, Lead } from "../types";
import { CrmDataProvider } from "../providers/supabase/dataProvider";
import { HumanReplyError } from "@/lib/vfic/humanReplyService";
import { useConversationActions } from "./useConversationActions";

type SenderKind = "candidate" | "bot" | "recruiter" | "system" | "tool";

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
  }
> = {
  candidate: {
    label: "Candidate",
    icon: UserIcon,
    bubble: "bg-muted text-foreground",
    align: "start",
  },
  bot: {
    label: "AI Bot",
    icon: Bot,
    bubble: "bg-blue-100 text-blue-950 dark:bg-blue-900/40 dark:text-blue-50",
    align: "end",
  },
  recruiter: {
    label: "Recruiter",
    icon: UserCircle,
    bubble: "bg-primary text-primary-foreground",
    align: "end",
  },
  system: {
    label: "System",
    icon: Sparkles,
    bubble:
      "bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-100",
    align: "center",
  },
  tool: {
    label: "Tool",
    icon: Wrench,
    bubble:
      "border border-dashed border-border bg-muted/60 text-muted-foreground",
    align: "center",
  },
};

const formatTime = (iso?: string) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-GB", {
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
            setError("Could not load the conversation. Please try again.");
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
      <div className="flex justify-center">
        <div
          className={cn(
            "max-w-md rounded-lg px-4 py-2 text-center text-xs shadow-sm",
            meta.bubble,
          )}
        >
          <div className="mb-0.5 flex items-center justify-center gap-1 font-semibold uppercase tracking-wide opacity-70">
            <Icon className="size-3" />
            {meta.label}
          </div>
          <div className="whitespace-pre-wrap text-sm">{msg.content}</div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex w-full",
        (meta.align as string) === "end" ? "justify-end" : "justify-start",
      )}
    >
      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-2.5 shadow-sm",
          meta.bubble,
        )}
      >
        <div
          className={cn(
            "mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide",
            "opacity-70",
          )}
        >
          <Icon className="size-3" />
          {meta.label}
          {showTime && msg.created_at && (
            <span className="ml-1 font-normal normal-case opacity-80">
              • {formatTime(msg.created_at)}
            </span>
          )}
        </div>
        <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
          {msg.content}
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
    <Card className="flex h-[calc(100vh-220px)] flex-col overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between gap-2 border-b px-4 py-3 md:px-6 md:py-4">
        <div className="flex min-w-0 items-center gap-3">
          <CardTitle className="flex items-center gap-2 truncate text-base">
            <Inbox className="size-4 shrink-0 text-muted-foreground" />
            <span className="truncate">
              {lead?.name ||
                `Unknown lead · ending ${(record.zalo_chat_id || "").slice(-4)}`}
            </span>
            {lead && (
              <span className="text-sm font-normal text-muted-foreground hidden sm:inline-block">
                · {lead.desired_job || "No job specified"} · {lead.lead_stage}
              </span>
            )}
          </CardTitle>
          <Badge
            variant={isBotMode ? "secondary" : "default"}
            className="shrink-0 gap-1"
          >
            {isBotMode ? (
              <>
                <Bot className="size-3" /> Bot
              </>
            ) : (
              <>
                <UserCircle className="size-3" /> Human
              </>
            )}
          </Badge>
        </div>
        <div className="flex shrink-0 gap-2">
          {isBotMode ? (
            <Button size="sm" onClick={handleTakeover} className="gap-2">
              <UserCircle className="size-4" />
              Take Over
            </Button>
          ) : (
            <Button
              size="sm"
              variant="outline"
              onClick={handleRelease}
              className="gap-2"
            >
              <Bot className="size-4" />
              Release to Bot
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col overflow-hidden p-0">
        {error ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <div className="flex max-w-sm flex-col items-center gap-2 text-center">
              <AlertTriangle className="size-8 text-destructive" />
              <p className="font-medium">Failed to load messages</p>
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
                <p className="font-medium">No messages yet</p>
                <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                  The chat history is empty. New messages from Zalo will appear
                  here in real time.
                </p>
              </div>
            </div>
          </div>
        ) : (
          <div
            className="flex-1 overflow-y-auto px-4 py-4 md:px-6"
            ref={scrollRef}
          >
            <div className="flex flex-col gap-2.5">
              {grouped.map(
                ({ msg, isFirstOfGroup, isInternalGroup, groupMessages }) => {
                  if (isInternalGroup && groupMessages) {
                    return (
                      <details key={msg.id} className="w-full my-2 text-center">
                        <summary className="cursor-pointer text-xs text-muted-foreground select-none opacity-80 hover:opacity-100 flex justify-center items-center list-none outline-none">
                          <span className="flex items-center gap-1">
                            <Sparkles className="size-3" />
                            AI activity · {groupMessages.length} actions
                          </span>
                        </summary>
                        <div className="w-full mt-3 flex flex-col gap-2.5">
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
          </div>
        )}

        <div className="border-t bg-background p-3 md:p-4">
          {isBotMode ? (
            <div className="mb-2 flex items-start gap-2 rounded-lg bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
              <Lock className="mt-0.5 size-3.5 shrink-0" />
              <span>
                The bot is currently handling this conversation. Take over to
                start replying manually.
              </span>
            </div>
          ) : null}
          <form onSubmit={handleSend} className="flex items-center gap-2">
            <Input
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              placeholder={
                isBotMode
                  ? "Take over the conversation to reply…"
                  : "Type your reply…"
              }
              disabled={isBotMode || isSending}
              className="flex-1"
              autoComplete="off"
            />
            <Button
              type="submit"
              size="icon"
              disabled={isBotMode || isSending || !reply.trim()}
              aria-label="Send message"
              title="Send message"
            >
              <Send className="size-4" />
            </Button>
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
        <h2 className="mr-auto text-xl font-semibold">Conversation</h2>
      </TopToolbar>
      <ConversationShowContent />
    </ShowBase>
  );
};
