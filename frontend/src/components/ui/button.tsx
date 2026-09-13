import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "tt-btn inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-[length:var(--fs-body-sm)] max-md:text-button font-semibold transition-[color,background-color,border-color,box-shadow,transform] disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
  {
    variants: {
      variant: {
        default:
          "tt-btn-primary text-[var(--color-primary-content)] shadow-xs",
        destructive:
          "tt-btn-error shadow-xs focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40",
        outline:
          "tt-btn-outline border shadow-xs hover:bg-accent hover:text-accent-foreground dark:border-input dark:hover:bg-input/50",
        secondary: "tt-btn-secondary tt-btn-soft shadow-xs",
        ghost:
          "tt-btn-ghost hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50",
        link: "tt-btn-link underline-offset-4 hover:underline",
      },
      size: {
        // Desktop uses a 28/32/36px action hierarchy; mobile expands every
        // interactive variant to the 44px touch target.
        default: "tt-btn-md h-8 max-md:h-11 px-3 has-[>svg]:px-2.5",
        sm: "tt-btn-sm h-7 rounded-md px-2.5 has-[>svg]:px-2 max-md:h-11 max-md:px-3",
        lg: "tt-btn-lg h-9 rounded-md px-4 has-[>svg]:px-3 max-md:h-11",
        touch: "tt-btn-touch tt-btn-lg h-11 px-4 py-2 has-[>svg]:px-3",
        icon: "tt-btn-square size-9 max-md:size-11",
        "icon-sm": "tt-btn-square tt-btn-sm size-8 max-md:size-11",
        "icon-touch": "tt-btn-touch tt-btn-square tt-btn-lg size-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot : "button"

  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
