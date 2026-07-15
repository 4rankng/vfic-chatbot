import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

type SetupSectionProps = {
  title: ReactNode
  description?: ReactNode
  trailing?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
  /** When true, the title sits inside a card-like surface; otherwise it floats. */
  surface?: boolean
}

/**
 * One labeled sub-section inside a step (e.g. "Chọn mẫu đã xuất bản",
 * "Tạo mẫu mới"). Wraps content in a single rounded card with consistent
 * padding so the wizard reads as one card per step rather than a wall of
 * nested borders.
 */
export const SetupSection = ({
  title,
  description,
  trailing,
  children,
  className,
  bodyClassName,
  surface = true,
}: SetupSectionProps) => {
  return (
    <section
      className={cn(
        "grid gap-4",
        surface &&
          "rounded-lg border border-border bg-card p-4 sm:p-5",
        className,
      )}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="grid min-w-0 gap-1">
          <h3 className="text-control font-semibold leading-tight text-foreground">
            {title}
          </h3>
          {description ? (
            <p className="text-meta text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {trailing ? <div className="shrink-0">{trailing}</div> : null}
      </header>
      <div className={cn("grid gap-4", bodyClassName)}>{children}</div>
    </section>
  )
}
