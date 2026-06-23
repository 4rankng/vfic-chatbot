import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

// Compact pill stack with overflow: shows the first `max` tags and collapses the
// rest into a "+N" pill whose tooltip lists every hidden label.
export type TagTone = "default" | "success" | "warning" | "destructive"

export interface TagStackTag {
  label: string
  tone?: TagTone
}

const toneClass: Record<TagTone, string> = {
  default: "bg-secondary text-secondary-foreground border-transparent",
  success:
    "bg-emerald-500/12 text-emerald-700 dark:text-emerald-400 border-emerald-500/20",
  warning:
    "bg-amber-500/12 text-amber-700 dark:text-amber-400 border-amber-500/20",
  destructive:
    "bg-rose-500/12 text-rose-700 dark:text-rose-400 border-rose-500/20",
}

function TagStack({
  tags,
  max = 2,
  className,
}: {
  tags: TagStackTag[]
  max?: number
  className?: string
}) {
  if (tags.length === 0) return null

  const visible = tags.slice(0, max)
  const overflow = tags.slice(max)

  return (
    <div className={cn("flex max-w-full items-center gap-1.5", className)}>
      {visible.map((tag, i) => (
        <Badge
          key={`${tag.label}-${i}`}
          variant="secondary"
          className={cn(
            "max-w-[160px] truncate",
            toneClass[tag.tone ?? "default"],
          )}
        >
          {tag.label}
        </Badge>
      ))}
      {overflow.length > 0 ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge
              variant="outline"
              className="shrink-0 cursor-default tabular-nums"
            >
              +{overflow.length}
            </Badge>
          </TooltipTrigger>
          <TooltipContent>{overflow.map((t) => t.label).join(" • ")}</TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  )
}

export { TagStack }
