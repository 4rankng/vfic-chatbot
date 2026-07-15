import { Check } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export type SetupStepperItem = {
  key: string
  label: string
  complete: boolean
}

export type SetupStepperProps = {
  items: ReadonlyArray<SetupStepperItem>
  currentIndex: number
  onSelect: (index: number) => void
  ariaLabel: string
  className?: string
}

export const SetupStepper = ({
  items,
  currentIndex,
  onSelect,
  ariaLabel,
  className,
}: SetupStepperProps) => {
  return (
    <nav
      aria-label={ariaLabel}
      data-slot="setup-stepper"
      className={cn(
        // Mobile/tablet: horizontal compact pill. Desktop: sticky vertical list.
        "grid gap-2 lg:sticky lg:top-20",
        "grid-flow-col auto-cols-fr lg:grid-flow-row lg:grid-cols-1",
        className,
      )}
    >
      {items.map((item, index) => {
        const isCurrent = currentIndex === index
        return (
          <button
            key={item.key}
            type="button"
            aria-current={isCurrent ? "step" : undefined}
            onClick={() => onSelect(index)}
            className={cn(
              "group flex min-h-11 min-w-0 items-center gap-3 rounded-lg border px-3 py-2 text-left transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              isCurrent
                ? "border-primary bg-primary text-primary-foreground shadow-xs"
                : "border-border bg-card hover:bg-muted text-foreground",
            )}
          >
            <span
              className={cn(
                "flex size-6 shrink-0 items-center justify-center rounded-full border text-helper font-semibold",
                item.complete
                  ? isCurrent
                    ? "border-primary-foreground/50 text-primary-foreground"
                    : "border-primary bg-primary text-primary-foreground"
                  : isCurrent
                    ? "border-primary-foreground/50 text-primary-foreground"
                    : "border-border text-muted-foreground",
              )}
              aria-hidden="true"
            >
              {item.complete ? <Check className="size-3.5" /> : index + 1}
            </span>
            <span
              className={cn(
                "min-w-0 truncate text-nav font-medium",
                isCurrent ? "text-primary-foreground" : "text-foreground",
              )}
            >
              {item.label}
            </span>
          </button>
        )
      })}
    </nav>
  )
}

export const SetupStepperInline = ({ children }: { children: ReactNode }) => (
  <div className="lg:hidden">{children}</div>
)
