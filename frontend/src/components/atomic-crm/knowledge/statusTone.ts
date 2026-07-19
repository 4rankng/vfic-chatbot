// Tailwind tone classes for a knowledge-source status. `status` is free text
// (default 'published'); unknown values fall back to muted.

export const statusTone = (status: string): string => {
  const s = status?.toLowerCase();
  if (s === "published") return "bg-success text-white";
  if (s === "draft" || s === "pending") return "bg-warning text-warning-foreground";
  if (s === "error" || s === "failed") return "bg-destructive text-white";
  return "bg-muted text-muted-foreground";
};
