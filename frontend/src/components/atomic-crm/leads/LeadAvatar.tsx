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
  "bg-gradient-to-br from-purple-400 to-indigo-500 text-white border-transparent",
  "bg-gradient-to-br from-pink-400 to-rose-400 text-white border-transparent",
  "bg-gradient-to-br from-emerald-400 to-teal-500 text-white border-transparent",
  "bg-gradient-to-br from-cyan-400 to-blue-500 text-white border-transparent",
  "bg-gradient-to-br from-orange-400 to-orange-600 text-white border-transparent",
  "bg-gradient-to-br from-violet-400 to-fuchsia-500 text-white border-transparent",
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
