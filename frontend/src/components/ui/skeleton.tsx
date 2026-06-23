import { cn } from "@/lib/utils"

function Skeleton({
  className,
  shimmer = false,
  ...props
}: React.ComponentProps<"div"> & { shimmer?: boolean }) {
  return (
    <div
      data-slot="skeleton"
      className={cn(
        "bg-accent rounded-md",
        shimmer ? "animate-shimmer" : "animate-pulse",
        className,
      )}
      {...props}
    />
  )
}

export { Skeleton }
