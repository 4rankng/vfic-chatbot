import { Skeleton } from "@/components/ui/skeleton";

import { AuthShell } from "./AuthShell";

/**
 * Suspense fallback for the code-split `/forgot-password` route. It renders on
 * the same `AuthShell` the resolved page paints (split hero + card column,
 * `min-h-svh`), so the route swap keeps the frame instead of jumping from a
 * centred 100vh stack — and `min-h-svh` also stops mobile browser chrome from
 * overflowing the fallback the way `h-screen` did.
 */
export const LoginSkeleton = () => (
  <AuthShell productName="TingHire">
    <div
      className="flex flex-col gap-3"
      role="status"
      aria-label="Đang tải biểu mẫu"
    >
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-[var(--form-control-height)] w-full" />
      <Skeleton className="h-[var(--form-control-height)] w-full" />
      <Skeleton className="h-[var(--form-control-height)] w-full" />
    </div>
  </AuthShell>
);
