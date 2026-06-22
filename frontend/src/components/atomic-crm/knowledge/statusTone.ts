// Tailwind tone classes for a knowledge-source status. `status` is free text
// (default 'published'); unknown values fall back to muted.

export const statusTone = (status: string): string => {
  const s = status?.toLowerCase();
  if (s === "published") return "bg-emerald-500 text-white";
  if (s === "draft" || s === "pending") return "bg-amber-500 text-white";
  if (s === "error" || s === "failed") return "bg-rose-500 text-white";
  return "bg-muted text-muted-foreground";
};
