import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

type LoadingStateProps = {
  label: string;
  className?: string;
  compact?: boolean;
};

/**
 * Consistent status feedback for waits where a content-shaped skeleton would
 * be misleading, such as a chat thread, a data refresh, or a toolbar count.
 */
export const LoadingState = ({
  label,
  className,
  compact = false,
}: LoadingStateProps) => (
  <div
    className={cn(
      "flex items-center justify-center text-muted-foreground",
      compact
        ? "gap-2 rounded-full border border-border/70 bg-background/80 px-3 py-1.5 text-caption font-medium shadow-xs"
        : "min-h-40 w-full flex-col gap-3 p-6 text-center text-body font-medium",
      className,
    )}
    role="status"
    aria-live="polite"
  >
    <Spinner
      size={compact ? "small" : "medium"}
      className={compact ? "size-3.5 text-primary" : "text-primary"}
    />
    <span>{label}</span>
  </div>
);
