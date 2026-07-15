import * as React from "react"

import { cn } from "@/lib/utils"

// Reusable empty/placeholder state: optional icon, title, description, and a
// slot for call-to-action buttons. Copy (Vietnamese) is supplied at call sites.
function EmptyState({
  icon,
  title,
  description,
  actions,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  icon?: React.ReactNode
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <div
      data-slot="empty-state"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border/60 bg-muted/20 px-6 py-12 text-center",
        className
      )}
      {...props}
    >
      {icon ? (
        <div className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
          {icon}
        </div>
      ) : null}
      <div className="space-y-1">
        <p className="text-card-title font-semibold text-foreground">{title}</p>
        {description ? (
          <p className="mx-auto max-w-sm text-helper text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex flex-wrap items-center justify-center gap-2">
          {actions}
        </div>
      ) : null}
    </div>
  )
}

export { EmptyState }
