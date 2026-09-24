import type {
  ExternalSourceSyncState,
  SinglePageExternalSourceSyncState,
} from "./project-knowledge-contracts";

/** A configured external source, in either the category or single-page shape. */
export type ExternalSourceRowState =
  | ExternalSourceSyncState
  | SinglePageExternalSourceSyncState;

/** Tailwind class for the status dot of a row. */
export const statusDotClass = (
  row: Pick<ExternalSourceRowState, "last_status">,
): string => {
  if (row.last_status === "FAILED") return "bg-destructive";
  if (row.last_status === "OK" || row.last_status === "NO_OP") {
    return "bg-primary";
  }
  if (row.last_status === "NEW" || row.last_status === "PROCESSING") {
    return "bg-amber-500";
  }
  return "bg-muted-foreground";
};

/** Tailwind class for the sync metadata line of a row. */
export const statusErrorClass = (
  row: Pick<ExternalSourceRowState, "last_status">,
): string =>
  row.last_status === "FAILED" ? "text-destructive" : "text-muted-foreground";

export const formatTimestamp = (value?: string | null): string => {
  if (!value) return "—";
  try {
    return new Intl.DateTimeFormat("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return value;
  }
};

export const formatCompactTimestamp = (value?: string | null): string => {
  if (!value) return "—";
  try {
    const date = new Date(value);
    const includeYear = date.getFullYear() !== new Date().getFullYear();
    const time = new Intl.DateTimeFormat("vi-VN", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
    const dateParts = new Intl.DateTimeFormat("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      ...(includeYear ? { year: "2-digit" as const } : {}),
    }).formatToParts(date);
    const part = (type: Intl.DateTimeFormatPartTypes) =>
      dateParts.find((item) => item.type === type)?.value ?? "";
    const day = [part("day"), part("month"), includeYear ? part("year") : ""]
      .filter(Boolean)
      .join("/");
    return `${time} · ${day}`;
  } catch {
    return value;
  }
};

export const truncate = (url: string, max = 48): string =>
  url.length > max ? `${url.slice(0, max)}…` : url;

/**
 * Everything about a row that moves when a sync makes progress. Polling uses it
 * to tell "still the row we started from" from "this row actually synced", and
 * the successful-sync signature derived from it drives the parent's refresh.
 */
export const rowProgressSignature = (row: ExternalSourceRowState): string =>
  [
    row.last_status,
    row.last_synced_at ?? "",
    row.last_content_hash ?? "",
    row.updated_at,
  ].join(":");

/** Signature of every row that currently holds successfully synced content. */
export const successfulSyncSignature = (
  rows: readonly ExternalSourceRowState[],
): string =>
  rows
    .filter((row) => row.last_status === "OK" || row.last_status === "NO_OP")
    .map((row) => `${row.id}:${rowProgressSignature(row)}`)
    .join("|");
