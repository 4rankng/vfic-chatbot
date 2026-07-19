import { cn } from "@/lib/utils";
import type { VariantProps } from "class-variance-authority";
import { cva } from "class-variance-authority";

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
});

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
});

interface SpinnerContentProps
  extends VariantProps<typeof spinnerVariants>,
    VariantProps<typeof loaderVariants> {
  className?: string;
}

/**
 * Animated spinner component for loading states.
 */
export function Spinner({ size, show, className }: SpinnerContentProps) {
  return (
    <span className={spinnerVariants({ show })}>
      <span
        className={cn(loaderVariants({ size }), className)}
        aria-hidden="true"
      />
    </span>
  );
}
