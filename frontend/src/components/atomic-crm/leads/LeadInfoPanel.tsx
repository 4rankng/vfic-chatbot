import {
  Briefcase,
  Calendar,
  CircleDollarSign,
  Copy,
  Hash,
  MessageSquare,
  Phone,
  User,
  Check,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useRecordContext } from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

import type { Lead } from "../types";
import { LeadScoreBar } from "./LeadScoreBar";
import { LeadStageBadge } from "./LeadStageBadge";
import { chatRepository } from "../conversations/chatRepository";

const formatDateTime = (iso?: string | null) => {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return new Intl.DateTimeFormat("vi-VN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(d);
  } catch {
    return null;
  }
};

const formatRelative = (iso?: string | null) => {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const diff = d.getTime() - Date.now();
  const abs = Math.abs(diff);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const rtf = new Intl.RelativeTimeFormat("vi", { numeric: "auto" });
  if (abs < hour) return rtf.format(Math.round(diff / minute), "minute");
  if (abs < day) return rtf.format(Math.round(diff / hour), "hour");
  if (abs < 30 * day) return rtf.format(Math.round(diff / day), "day");
  return rtf.format(Math.round(diff / day), "day");
};

const Copyable = ({ value }: { value: string }) => {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  };
  return (
    <button
      type="button"
      onClick={onCopy}
      title="Sao chép"
      className="inline-flex items-center justify-center rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {copied ? (
        <Check className="size-3.5 text-emerald-500" />
      ) : (
        <Copy className="size-3.5" />
      )}
    </button>
  );
};

const InfoRow = ({
  icon,
  label,
  value,
  monospace,
  href,
  copyable,
  emptyHint,
}: {
  icon: ReactNode;
  label: string;
  value?: ReactNode;
  monospace?: boolean;
  href?: string;
  copyable?: boolean;
  emptyHint?: string;
}) => {
  const empty = value === undefined || value === null || value === "";
  return (
    <div className="flex items-start gap-3 py-2.5">
      <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
        <div
          className={cn(
            "mt-0.5 flex items-center gap-2 text-sm",
            monospace && "font-mono tabular-nums",
            empty && "italic text-muted-foreground",
          )}
        >
          {empty ? (
            <span className="text-xs">{emptyHint ?? "Chưa cung cấp"}</span>
          ) : href ? (
            <a
              href={href}
              className="text-foreground underline-offset-4 hover:underline"
              target={href.startsWith("http") ? "_blank" : undefined}
              rel={href.startsWith("http") ? "noopener noreferrer" : undefined}
            >
              {value}
            </a>
          ) : (
            <span className="text-foreground">{value}</span>
          )}
          {!empty && copyable && typeof value === "string" && (
            <Copyable value={value} />
          )}
        </div>
      </div>
    </div>
  );
};

export const LeadInfoPanel = ({ className }: { className?: string }) => {
  const record = useRecordContext<Lead>();
  // Derived activity signal: total messages in this contact's Zalo thread.
  // Hooks must run before the early return below.
  const [messageCount, setMessageCount] = useState<number | null>(null);
  useEffect(() => {
    if (!record?.zalo_id) {
      setMessageCount(null);
      return;
    }
    let cancelled = false;
    chatRepository
      .getMessageCount(record.zalo_id)
      .then((n) => {
        if (!cancelled) setMessageCount(n);
      })
      .catch(() => {
        if (!cancelled) setMessageCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [record?.zalo_id]);
  if (!record) return null;

  const created = formatDateTime(record.created_at);
  const updated = formatDateTime(record.updated_at);
  const updatedRelative = formatRelative(record.updated_at);

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <User className="size-4 text-muted-foreground" />
            Thông tin khách hàng
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col">
          <InfoRow
            icon={<User className="size-4" />}
            label="Họ tên"
            value={record.name}
          />
          <Separator />
          <InfoRow
            icon={<Phone className="size-4" />}
            label="Số điện thoại"
            value={record.phone}
            href={
              record.phone
                ? `tel:${record.phone.replace(/\s+/g, "")}`
                : undefined
            }
            copyable
          />
          <Separator />
          <InfoRow
            icon={<MessageSquare className="size-4" />}
            label="Zalo ID"
            value={record.zalo_id}
            monospace
            copyable
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Briefcase className="size-4 text-muted-foreground" />
            Công việc &amp; mức lương
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col">
          <InfoRow
            icon={<Briefcase className="size-4" />}
            label="Công việc mong muốn"
            value={record.desired_job}
          />
          <Separator />
          <InfoRow
            icon={<CircleDollarSign className="size-4" />}
            label="Lương mong muốn"
            value={record.expected_salary}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Hash className="size-4 text-muted-foreground" />
            Đánh giá
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
              <Hash className="size-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Giai đoạn quy trình
              </div>
              <div className="mt-1">
                <LeadStageBadge stage={record.lead_stage} />
              </div>
            </div>
          </div>
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
              <Hash className="size-4" />
            </div>
            <div className="min-w-0 flex-1">
              <LeadScoreBar score={record.lead_score} />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Calendar className="size-4 text-muted-foreground" />
            Dòng thời gian
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col">
          <InfoRow
            icon={<Calendar className="size-4" />}
            label="Ngày tạo"
            value={created}
            emptyHint="Không rõ"
          />
          <Separator />
          <InfoRow
            icon={<Calendar className="size-4" />}
            label="Cập nhật lần cuối"
            value={updated ? `${updated} (${updatedRelative})` : undefined}
            emptyHint="Chưa bao giờ"
          />
          <Separator />
          <InfoRow
            icon={<MessageSquare className="size-4" />}
            label="Tổng tin nhắn"
            value={messageCount === null ? undefined : `${messageCount}`}
            emptyHint="Đang tải…"
          />
          {record.phone && (
            <>
              <Separator />
              <div className="flex items-center gap-2 pt-2.5">
                <a
                  href={`tel:${record.phone.replace(/\s+/g, "")}`}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                >
                  <Phone className="size-3.5" />
                  Gọi lại
                </a>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
