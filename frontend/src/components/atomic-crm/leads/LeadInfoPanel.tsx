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
import { useState, type ReactNode } from "react";
import { useRecordContext } from "ra-core";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

import type { Lead } from "../types";
import { LeadScoreBar } from "./LeadScoreBar";
import { LeadStageBadge } from "./LeadStageBadge";

const formatDateTime = (iso?: string | null) => {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return new Intl.DateTimeFormat("en-GB", {
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
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
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
      title="Copy"
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
            <span className="text-xs">{emptyHint ?? "Not provided"}</span>
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
            Lead Information
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col">
          <InfoRow
            icon={<User className="size-4" />}
            label="Full name"
            value={record.name}
          />
          <Separator />
          <InfoRow
            icon={<Phone className="size-4" />}
            label="Phone"
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
            Job &amp; Compensation
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col">
          <InfoRow
            icon={<Briefcase className="size-4" />}
            label="Desired job"
            value={record.desired_job}
          />
          <Separator />
          <InfoRow
            icon={<CircleDollarSign className="size-4" />}
            label="Expected salary"
            value={record.expected_salary}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Hash className="size-4 text-muted-foreground" />
            Qualification
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
              <Hash className="size-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Pipeline stage
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
            Timeline
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col">
          <InfoRow
            icon={<Calendar className="size-4" />}
            label="Created"
            value={created}
            emptyHint="Unknown"
          />
          <Separator />
          <InfoRow
            icon={<Calendar className="size-4" />}
            label="Last updated"
            value={updated ? `${updated} (${updatedRelative})` : undefined}
            emptyHint="Never"
          />
        </CardContent>
      </Card>
    </div>
  );
};
