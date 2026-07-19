import { cn } from "@/lib/utils"
import type { VariantProps } from "class-variance-authority"
import { cva } from "class-variance-authority"
import React from "react"

const spinnerVariants = cva("flex-col items-center justify-center", {
  variants: {
    show: {
      true: "flex",
      false: "hidden",
    },
  },
  defaultVariants: {
    show: true,
  },
})

const loaderVariants = cva("tt-loading tt-loading-spinner text-primary", {
  variants: {
    size: {
      small: "tt-loading-sm size-5",
      medium: "tt-loading-md size-6",
      large: "tt-loading-lg size-8",
    },
  },
  defaultVariants: {
    size: "medium",
  },
})

interface SpinnerContentProps
  extends VariantProps<typeof spinnerVariants>,
    VariantProps<typeof loaderVariants> {
  className?: string
  children?: React.ReactNode
}

export function Spinner({
  size,
  show,
  children,
  className,
}: SpinnerContentProps) {
  return (
    <span className={spinnerVariants({ show })}>
      <span
        className={cn(loaderVariants({ size }), className)}
        aria-hidden="true"
      />
      {children}
    </span>
  )
}
