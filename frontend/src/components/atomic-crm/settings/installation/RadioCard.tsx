import { forwardRef, type ReactNode } from "react"

import { cn } from "@/lib/utils"

type RadioCardProps = {
  name: string
  value: string
  checked: boolean
  onChange: () => void
  title: ReactNode
  description?: ReactNode
  disabled?: boolean
  className?: string
}

/**
 * A clickable card-style radio row. Wraps a native radio input so the field is
 * fully keyboard-operable, with a focus ring driven by the input's
 * focus-within state — matching every other selectable control in the wizard.
 */
export const RadioCard = forwardRef<HTMLInputElement, RadioCardProps>(
  function RadioCard(
    { name, value, checked, onChange, title, description, disabled, className },
    ref,
  ) {
    return (
      <label
        className={cn(
          "flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border bg-card p-4 text-left transition-colors",
          "hover:bg-muted/60",
          "focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/50",
          checked && "border-primary bg-primary/5",
          disabled && "cursor-not-allowed opacity-60",
          className,
        )}
      >
        <input
          ref={ref}
          type="radio"
          name={name}
          value={value}
          checked={checked}
          disabled={disabled}
          onChange={onChange}
          className="mt-1 size-4 shrink-0 cursor-pointer border-input text-primary accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        />
        <span className="grid min-w-0 gap-0.5">
          <span className="text-label font-semibold text-foreground">{title}</span>
          {description ? (
            <span className="text-helper text-muted-foreground">{description}</span>
          ) : null}
        </span>
      </label>
    )
  },
)
