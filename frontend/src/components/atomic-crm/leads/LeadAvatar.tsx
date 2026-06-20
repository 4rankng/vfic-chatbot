import {
  AvatarFallback,
  AvatarImage,
  Avatar as ShadcnAvatar,
} from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import { useRecordContext } from "ra-core";

import type { Lead } from "../types";

const initials = (name?: string) => {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].charAt(0).toUpperCase();
  return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
};

const palette = [
  "bg-rose-500/15 text-rose-700 dark:text-rose-300",
  "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  "bg-cyan-500/15 text-cyan-700 dark:text-cyan-300",
  "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  "bg-indigo-500/15 text-indigo-700 dark:text-indigo-300",
  "bg-purple-500/15 text-purple-700 dark:text-purple-300",
  "bg-pink-500/15 text-pink-700 dark:text-pink-300",
];

const paletteFor = (seed?: string) => {
  if (!seed) return palette[0];
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return palette[h % palette.length];
};

export const LeadAvatar = ({
  record,
  size = "md",
  className,
}: {
  record?: Lead;
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
}) => {
  const ctx = useRecordContext<Lead>();
  const r = record ?? ctx;
  const sizeClass =
    size === "xl"
      ? "size-20 text-2xl"
      : size === "lg"
        ? "size-14 text-lg"
        : size === "sm"
          ? "size-8 text-xs"
          : "size-10 text-sm";
  if (!r) return null;
  return (
    <ShadcnAvatar
      className={cn(
        sizeClass,
        "font-semibold ring-1 ring-border",
        paletteFor(r.name),
        className,
      )}
    >
      <AvatarImage src={(r as any).avatar?.src} alt={r.name} />
      <AvatarFallback className="bg-transparent">
        {initials(r.name)}
      </AvatarFallback>
    </ShadcnAvatar>
  );
};
