import { ShowBase, useShowContext, useDataProvider } from "ra-core";
import type { ShowBaseProps } from "ra-core";
import { useIsMobile } from "@/hooks/use-mobile";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { EditButton } from "@/components/admin/edit-button";
import { RefreshButton } from "@/components/admin/refresh-button";
import { DeleteButton } from "@/components/admin";
import { TopToolbar } from "../layout/TopToolbar";
import { chatRepository } from "../conversations/chatRepository";
import { ChatThread } from "../conversations/ChatThread";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Lead, Conversation, Message } from "../types";
import { LeadAvatar } from "./LeadAvatar";
import { LeadBreadcrumb } from "./LeadBreadcrumb";
import { LeadInfoPanel } from "./LeadInfoPanel";
import { LeadScoreBar } from "./LeadScoreBar";
import { LeadStageBadge } from "./LeadStageBadge";
import { useLeadPresence, type ViewerInfo } from "./useLeadPresence";
import {
  Bot,
  Briefcase,
  Calendar,
  Check,
  CircleDollarSign,
  Copy,
  Eye,
  Hash,
  MapPin,
  MessageSquare,
  Phone,
  User,
} from "lucide-react";
import { cn } from "@/lib/utils";

const PresenceViewers = ({
  viewers,
  typingUsers,
}: {
  viewers: ViewerInfo[];
  typingUsers: ViewerInfo[];
}) => {
  if (viewers.length === 0 && typingUsers.length === 0) return null;
  const names = viewers.map((v) => v.name || "Nhân viên").join(", ");
  return (
    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <Eye className="size-3" />
      <span>{names} đang xem</span>
      {typingUsers.length > 0 && (
        <span className="text-primary">
          {" · "}
          {typingUsers.map((u) => u.name || "Nhân viên").join(", ")} đang
          nhập...
        </span>
      )}
    </div>
  );
};

const LeadChat = ({ zaloId }: { zaloId: string }) => {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const dataProvider = useDataProvider<any>();

  useEffect(() => {
    let cancelled = false;
    if (!zaloId) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setError(null);

    Promise.resolve(
      dataProvider.getList("conversations", {
        filter: { zalo_chat_id: zaloId },
        pagination: { page: 1, perPage: 1 },
        sort: { field: "updated_at", order: "DESC" },
      }),
    )
      .then(({ data }: { data: Conversation[] }) => {
        if (cancelled) return;
        setConversation(data?.[0] ?? null);
        setIsLoading(false);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const msg =
          e instanceof Error ? e.message : "Không thể tải cuộc trò chuyện";
        setError(msg);
        setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [zaloId, dataProvider]);

  if (isLoading) {
    return (
      <Card className="flex h-[min(620px,calc(100dvh-160px))] flex-col lg:h-[calc(100vh-220px)]">
        <CardHeader className="border-b">
          <Skeleton className="h-5 w-48" />
        </CardHeader>
        <CardContent className="flex flex-1 flex-col gap-4 p-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className={cn(
                "flex w-full",
                i % 2 === 0 ? "justify-start" : "justify-end",
              )}
            >
              <Skeleton
                className={cn(
                  "h-16 rounded-lg",
                  i % 2 === 0 ? "w-1/2" : "w-2/5",
                )}
              />
            </div>
          ))}
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="flex h-[min(620px,calc(100dvh-160px))] flex-col items-center justify-center p-6 lg:h-[calc(100vh-220px)]">
        <div className="text-center text-sm text-muted-foreground">
          <p className="font-medium text-destructive">
            Không thể tải cuộc trò chuyện
          </p>
          <p className="mt-1 text-xs">{error}</p>
        </div>
      </Card>
    );
  }

  if (!conversation) {
    return (
      <Card className="flex h-[min(620px,calc(100dvh-160px))] flex-col items-center justify-center p-6 lg:h-[calc(100vh-220px)]">
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="rounded-full bg-muted p-4">
            <Bot className="size-8 text-muted-foreground" />
          </div>
          <div>
            <p className="text-base font-medium">Chưa có cuộc trò chuyện</p>
            <p className="mt-1 max-w-sm text-sm text-muted-foreground">
              Khi ứng viên này bắt đầu trò chuyện trên Zalo, cuộc trò chuyện sẽ
              hiển thị tại đây.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    // .chat-surface establishes the chat-element CSS scope (mirrors the inbox's
    // .inbox-bg-container) and the grid gives the virtualised scroller a real
    // height — the missing piece that broke the old ConversationShowContent
    // embed, which was an inbox-shell pane that only rendered inside
    // /conversations. Same <ChatThread> the inbox uses, so behaviour is
    // identical (realtime, reply, takeover, markAsRead).
    <div className="chat-surface grid h-[min(620px,calc(100dvh-160px))] grid-rows-[minmax(0,1fr)_auto] overflow-hidden rounded-xl border border-border bg-card lg:h-[calc(100vh-220px)]">
      <ChatThread
        conversationId={conversation?.id ?? ""}
        conversation={conversation}
      />
    </div>
  );
};

const LeadHero = () => {
  const { record, isPending } = useShowContext<Lead>();
  if (isPending || !record) return null;

  return (
    <Card>
      <CardContent className="flex flex-col gap-5 p-6 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-4">
          <LeadAvatar size="xl" />
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-bold tracking-tight">
              {record.name || "Chưa rõ tên ứng viên"}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
              {record.phone && (
                <span className="inline-flex items-center gap-1">
                  {record.phone}
                </span>
              )}
              {record.desired_job && (
                <span className="inline-flex items-center gap-1">
                  <span className="text-muted-foreground/50">•</span>
                  {record.desired_job}
                </span>
              )}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <LeadStageBadge stage={record.lead_stage} />
              <LeadScoreBar score={record.lead_score} className="w-32" />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

export const LeadShowContent = () => {
  const { record, isPending, isLoading, refetch } = useShowContext<Lead>();
  const presence = useLeadPresence(record?.id);

  // Auto-refresh when lead.updated event arrives from another recruiter
  useEffect(() => {
    const handler = () => refetch();
    window.addEventListener("vfic:lead-updated", handler);
    return () => window.removeEventListener("vfic:lead-updated", handler);
  }, [refetch]);

  if (isPending) {
    return (
      <div className="mt-2 flex flex-col gap-4">
        <Skeleton className="h-32 w-full rounded-xl" />
        <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
          <div className="flex flex-col gap-4">
            <Skeleton className="h-64 w-full rounded-xl" />
            <Skeleton className="h-32 w-full rounded-xl" />
          </div>
          <Skeleton className="h-[min(620px,calc(100dvh-160px))] w-full rounded-xl lg:h-[calc(100vh-220px)]" />
        </div>
      </div>
    );
  }
  if (isLoading || !record) return null;

  return (
    <div className="mt-2 flex flex-col gap-4">
      <LeadHero />
      <PresenceViewers
        viewers={presence.viewers}
        typingUsers={presence.typingUsers}
      />
      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <div className="flex flex-col gap-4">
          <LeadInfoPanel />
        </div>
        <div className="flex flex-col">
          <LeadChat zaloId={record.zalo_id} />
        </div>
      </div>
    </div>
  );
};

export const LeadShowContentMobile = () => {
  const { record, isPending, isLoading, refetch } = useShowContext<Lead>();
  const presence = useLeadPresence(record?.id);

  useEffect(() => {
    const handler = () => refetch();
    window.addEventListener("vfic:lead-updated", handler);
    return () => window.removeEventListener("vfic:lead-updated", handler);
  }, [refetch]);

  if (isPending) {
    return (
      <div className="flex flex-col gap-3 p-2">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-40 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }
  if (isLoading || !record) return null;

  return (
    <div className="flex flex-col gap-3">
      <section className="border-b border-border pb-3">
        <div className="flex items-center gap-3">
          <LeadAvatar size="lg" />
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-lg font-semibold">
              {record.name || "Chưa rõ tên ứng viên"}
            </h1>
            <div className="text-xs text-muted-foreground">
              {record.phone || "Chưa có số điện thoại"}
            </div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <LeadStageBadge stage={record.lead_stage} />
          <LeadScoreBar score={record.lead_score} className="min-w-32 flex-1" />
        </div>
        {record.desired_job && (
          <div className="mt-2 text-sm text-muted-foreground">
            {record.desired_job}
          </div>
        )}
      </section>
      <PresenceViewers
        viewers={presence.viewers}
        typingUsers={presence.typingUsers}
      />
      <LeadInfoPanel />
      <LeadChat zaloId={record.zalo_id} />
    </div>
  );
};

// ---- Drawer (Sheet) variants ------------------------------------------------
// The leads list opens a lead in a right-side Sheet (see LeadListContent). The
// full-page LeadShow layout (two-column grid + embedded live chat) does not fit
// a narrow drawer, and the live chat (ConversationShowContent) is an inbox-shell
// pane that only renders correctly inside /conversations. So the drawer is a
// single-column DETAIL PEEK: hero + info + a read-only preview of the most
// recent messages, with a footer CTA that deep-links to the full, reply-able
// thread on /conversations. No realtime subscription, no markAsRead — a peek
// must not clear the unread badge.

const formatClock = (iso?: string | null): string => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
};

const formatDateTimeCompact = (iso?: string | null): string => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
};

const cleanText = (value?: string | number | null) => {
  if (value === undefined || value === null) return "";
  return String(value).trim();
};

const CompactCopy = ({ value }: { value: string }) => {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1200);
    return () => clearTimeout(timer);
  }, [copied]);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      /* best effort */
    }
  };

  return (
    <button
      type="button"
      className="inline-flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      onClick={handleCopy}
      title="Sao chép"
      aria-label="Sao chép"
    >
      {copied ? (
        <Check className="size-3.5 text-emerald-600" />
      ) : (
        <Copy className="size-3.5" />
      )}
    </button>
  );
};

const CompactFact = ({
  icon,
  label,
  value,
  copyable,
  mono,
  className,
}: {
  icon: ReactNode;
  label: string;
  value?: string | null;
  copyable?: boolean;
  mono?: boolean;
  className?: string;
}) => {
  const text = cleanText(value);
  return (
    <div
      className={cn(
        "grid min-w-0 grid-cols-[1rem_minmax(0,1fr)] gap-x-2 gap-y-0.5 border-b border-border/70 px-3 py-2 last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0",
        className,
      )}
    >
      <span className="mt-0.5 text-muted-foreground">{icon}</span>
      <div className="min-w-0">
        <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
        <div
          className={cn(
            "mt-0.5 flex min-w-0 items-center gap-1.5 text-[13px] leading-5",
            text ? "text-foreground" : "italic text-muted-foreground",
            mono && "font-mono tabular-nums",
          )}
        >
          <span className="min-w-0 truncate">{text || "Chưa cung cấp"}</span>
          {text && copyable && <CompactCopy value={text} />}
        </div>
      </div>
    </div>
  );
};

const CompactLeadDrawerDetails = ({ lead }: { lead: Lead }) => {
  const location = [cleanText(lead.region), cleanText(lead.living_area)]
    .filter(Boolean)
    .join(" · ");
  const created = formatDateTimeCompact(lead.created_at);
  const updated = formatDateTimeCompact(lead.updated_at);
  const displayName = cleanText(lead.name) || "Chưa rõ tên ứng viên";
  const job = cleanText(lead.desired_job);

  return (
    <div className="flex flex-col gap-3">
      <section className="rounded-lg border border-border bg-card/80 px-3 py-3">
        <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-3">
          <LeadAvatar record={lead} size="lg" className="size-12" />
          <div className="min-w-0">
            <div className="flex min-w-0 items-start justify-between gap-2">
              <div className="min-w-0">
                <h2 className="truncate text-xl font-bold leading-6 tracking-tight text-foreground">
                  {displayName}
                </h2>
                <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                  {lead.phone && <span>{lead.phone}</span>}
                  {lead.phone && job && <span aria-hidden>·</span>}
                  {job && <span className="truncate">{job}</span>}
                </div>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <LeadStageBadge stage={lead.lead_stage} className="h-6 text-xs" />
              <LeadScoreBar
                score={lead.lead_score}
                className="h-6 text-[10px]"
              />
            </div>
          </div>
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-border bg-card/80">
        <div className="grid sm:grid-cols-2">
          <CompactFact
            icon={<Phone className="size-4" />}
            label="Điện thoại"
            value={lead.phone}
            copyable
          />
          <CompactFact
            icon={<MessageSquare className="size-4" />}
            label="Zalo ID"
            value={lead.zalo_id}
            copyable
            mono
          />
          <CompactFact
            icon={<Briefcase className="size-4" />}
            label="Công việc"
            value={lead.desired_job}
          />
          <CompactFact
            icon={<CircleDollarSign className="size-4" />}
            label="Lương"
            value={lead.expected_salary}
          />
          <CompactFact
            icon={<MapPin className="size-4" />}
            label="Khu vực"
            value={location}
          />
          <CompactFact
            icon={<User className="size-4" />}
            label="Kinh nghiệm"
            value={lead.years_experience}
          />
          <CompactFact
            icon={<Calendar className="size-4" />}
            label="Tạo"
            value={created}
          />
          <CompactFact
            icon={<Calendar className="size-4" />}
            label="Cập nhật"
            value={updated}
          />
          {lead.notes && (
            <CompactFact
              icon={<Hash className="size-4" />}
              label="Ghi chú"
              value={lead.notes}
              className="sm:col-span-2 sm:[&:nth-last-child(-n+2)]:border-b sm:!border-b-0"
            />
          )}
        </div>
      </section>
    </div>
  );
};

type PreviewStatus = "loading" | "empty" | "error" | "ready";

const LeadChatPreview = ({
  messages,
  status,
  onRetry,
}: {
  messages: Message[];
  status: PreviewStatus;
  onRetry: () => void;
}) => {
  const title = (
    <CardTitle className="flex items-center gap-2 text-base">
      <MessageSquare className="size-4 text-muted-foreground" />
      Tin nhắn gần đây
    </CardTitle>
  );

  if (status === "loading") {
    return (
      <Card className="gap-2 rounded-lg py-3">
        <CardHeader className="px-3 pb-0">{title}</CardHeader>
        <CardContent className="flex flex-col gap-1.5 px-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-7 w-full rounded-md" />
          ))}
        </CardContent>
      </Card>
    );
  }

  if (status === "empty") {
    return (
      <Card className="rounded-lg py-0">
        <CardContent className="flex items-center gap-3 px-3 py-3">
          <div className="shrink-0 rounded-md bg-muted p-2">
            <Bot className="size-5 text-muted-foreground" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium leading-5">Chưa có tin nhắn</p>
            <p className="truncate text-xs text-muted-foreground">
              Nội dung Zalo sẽ hiển thị tại đây.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (status === "error") {
    return (
      <Card className="rounded-lg py-0">
        <CardContent className="flex items-center justify-between gap-3 px-3 py-3">
          <p className="text-sm font-medium text-destructive">
            Không thể tải tin nhắn
          </p>
          <Button variant="outline" size="sm" onClick={onRetry}>
            Thử lại
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="gap-2 rounded-lg py-3" aria-label="Tin nhắn gần đây">
      <CardHeader className="px-3 pb-0">{title}</CardHeader>
      <CardContent className="flex flex-col gap-1.5 px-3" aria-live="polite">
        {messages.map((m) => {
          const outbound = m.type === "outbound";
          return (
            <div key={m.id} className="flex items-start gap-2 text-sm">
              <span
                className={cn(
                  "mt-1 shrink-0 text-xs",
                  outbound ? "text-primary" : "text-muted-foreground",
                )}
                aria-hidden
              >
                {outbound ? "↗" : "↙"}
              </span>
              <span className="min-w-0 flex-1">
                <span
                  className={cn(
                    "block truncate rounded-md px-2.5 py-1.5",
                    outbound
                      ? "bg-primary/10 text-foreground"
                      : "bg-muted text-muted-foreground",
                  )}
                >
                  {m.content?.trim() || "…"}
                </span>
              </span>
              <span className="mt-1 shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground/70">
                {formatClock(m.created_at)}
              </span>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
};

// Drawer-native detail layout. Owns the conversation + message lookups so the
// footer CTA (deep-link) and the preview share one fetch. Rendered as the only
// child of the Sheet body; its root is a flex column that fills the sheet
// height — body scrolls, footer stays pinned.
export const LeadShowContentSheet = () => {
  const { record, isPending } = useShowContext<Lead>();
  const dataProvider = useDataProvider<any>();

  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState<PreviewStatus>("loading");
  const [retryNonce, setRetryNonce] = useState(0);

  const zaloId = record?.zalo_id;

  useEffect(() => {
    if (isPending) return;
    if (!zaloId) {
      setConversationId(null);
      setMessages([]);
      setStatus("empty");
      return;
    }
    let cancelled = false;
    setStatus("loading");
    setConversationId(null);

    Promise.resolve(
      dataProvider.getList("conversations", {
        filter: { zalo_chat_id: zaloId },
        pagination: { page: 1, perPage: 1 },
        sort: { field: "updated_at", order: "DESC" },
      }),
    )
      .then(({ data }: { data: Conversation[] }) => {
        if (cancelled) return;
        const conv = data?.[0] ?? null;
        if (!conv?.id) {
          setStatus("empty");
          return null;
        }
        setConversationId(conv.id);
        return chatRepository.getConversationMessages(conv.id, { limit: 3 });
      })
      .then((res) => {
        if (cancelled || !res) return;
        const msgs = res.messages ?? [];
        setMessages(msgs);
        setStatus(msgs.length > 0 ? "ready" : "empty");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [zaloId, isPending, dataProvider, retryNonce]);

  if (isPending) {
    return (
      <div className="flex flex-col gap-3 p-3 md:p-4">
        <Skeleton className="h-20 w-full rounded-lg" />
        <Skeleton className="h-48 w-full rounded-lg" />
        <Skeleton className="h-24 w-full rounded-lg" />
      </div>
    );
  }
  if (!record) return null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3 md:p-4">
        <CompactLeadDrawerDetails lead={record} />
        <LeadChatPreview
          messages={messages}
          status={status}
          onRetry={() => setRetryNonce((n) => n + 1)}
        />
      </div>
      {conversationId && (
        <div className="shrink-0 border-t border-border bg-card/95 p-3 backdrop-blur supports-[backdrop-filter]:bg-card/80">
          <Button asChild className="h-10 w-full text-sm font-semibold">
            <Link to={`/conversations?id=${conversationId}`}>
              <MessageSquare className="size-4" />
              Mở cuộc trò chuyện
            </Link>
          </Button>
        </div>
      )}
    </div>
  );
};

export const LeadShow = (props: ShowBaseProps = {}) => {
  const isMobile = useIsMobile();
  return (
    <ShowBase {...props}>
      <div className="flex flex-col gap-3">
        <LeadBreadcrumb />
        <TopToolbar>
          <h2 className="mr-auto text-xl font-semibold">Ứng viên</h2>
          <RefreshButton />
          <EditButton />
          <DeleteButton
            className="h-6 cursor-pointer hover:bg-destructive/10! text-destructive! border-destructive! focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40"
            size="sm"
          />
        </TopToolbar>
        {isMobile ? <LeadShowContentMobile /> : <LeadShowContent />}
      </div>
    </ShowBase>
  );
};
