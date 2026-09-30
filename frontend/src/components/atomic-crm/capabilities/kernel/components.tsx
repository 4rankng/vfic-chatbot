import { Component, lazy, Suspense } from "react";
import type { ComponentType, ReactNode } from "react";
import { Navigate } from "react-router";
import { usePermissions } from "ra-core";

// Route pages sit behind React.lazy so each screen stays its own chunk;
// a static import would pull settings, login and the admin performance page
// into the eager graph (index.test.ts pins "not statically imported").
export const ProfilePage = lazy(async () => {
  const module = await import("../../settings/ProfilePage");
  return { default: module.ProfilePage as ComponentType };
});
export const ForgotPasswordPage = lazy(async () => {
  const module = await import("../../login/ForgotPasswordPage");
  return { default: module.ForgotPasswordPage as ComponentType };
});
const PerformancePage = lazy(async () => {
  const module = await import("../../performance/PerformancePage");
  return { default: module.PerformancePage as ComponentType };
});

const RouteLoadingState = () => (
  <div
    role="status"
    aria-live="polite"
    className="p-6 text-sm text-muted-foreground"
  >
    Đang tải trang...
  </div>
);

class RouteErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div role="alert" className="p-8 text-center text-muted-foreground">
        <p className="mb-3">Không thể tải trang. Vui lòng tải lại.</p>
        <button
          type="button"
          className="min-h-10 rounded-md border border-border px-4 py-2 text-button font-medium transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={() => window.location.reload()}
        >
          Tải lại trang
        </button>
      </div>
    );
  }
}

export const RouteBoundary = ({ children }: { children: ReactNode }) => (
  <RouteErrorBoundary>
    <Suspense fallback={<RouteLoadingState />}>{children}</Suspense>
  </RouteErrorBoundary>
);

export const AdminPerformanceRoute = () => {
  const { permissions, isPending } = usePermissions();
  if (isPending) return <RouteLoadingState />;
  return permissions === "admin" ? (
    <PerformancePage />
  ) : (
    <Navigate to="/" replace />
  );
};
