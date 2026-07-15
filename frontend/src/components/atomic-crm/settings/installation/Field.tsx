import { forwardRef, useId, type ReactNode } from "react"

import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"

type FieldProps = {
  label: ReactNode
  description?: ReactNode
  helper?: ReactNode
  error?: ReactNode
  required?: boolean
  htmlFor?: string
  children: (ids: { id: string; describedBy?: string; invalid?: boolean }) => ReactNode
  className?: string
  /** Column span inside a 2-col grid (e.g. "sm:col-span-2"). */
  colSpan?: string
}

/**
 * A single labelled control slot. Owns the id wiring (label + control + helper
 * + error), the gap between label and control, and the visual treatment that
 * matches the rest of the installation form.
 *
 * Render-prop API: children(id, describedBy, invalid) — passes the auto id and
 * aria-describedby string so any control can be plugged in without owning the
 * id bookkeeping.
 */
export const Field = forwardRef<HTMLDivElement, FieldProps>(function Field(
  { label, description, helper, error, required, htmlFor, children, className, colSpan },
  ref,
) {
  const reactId = useId()
  const id = htmlFor ?? `setup-field-${reactId}`
  const helperId = helper ? `${id}-helper` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [helperId, errorId].filter(Boolean).join(" ") || undefined

  return (
    <div ref={ref} className={cn("grid gap-2", colSpan, className)}>
      <Label htmlFor={id}>
        {required ? `${label} *` : label}
      </Label>
      {description ? (
        <p className="text-helper text-muted-foreground">{description}</p>
      ) : null}
      {children({ id, describedBy, invalid: Boolean(error) })}
      {helper ? (
        <p id={helperId} className="text-helper text-muted-foreground">
          {helper}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="text-helper font-medium text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
})
