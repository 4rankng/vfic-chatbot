import { Error } from "@/components/admin/error";
import { Notification } from "@/components/admin/notification";
import { Skeleton } from "@/components/ui/skeleton";
import { Suspense, type ReactNode } from "react";
import { ErrorBoundary } from "react-error-boundary";
import { useLocation } from "react-router";
import { cn } from "@/lib/utils";

import { useConfigurationLoader } from "../root/useConfigurationLoader";
import { MobileNavigation } from "./MobileNavigation";

export const MobileLayout = ({ children }: { children: ReactNode }) => {
  useConfigurationLoader();
  const location = useLocation();
  const hashPath =
    typeof window === "undefined"
      ? ""
      : window.location.hash.replace(/^#/, "").split("?")[0];
  const isConversationRoute =
    location.pathname.startsWith("/conversations") ||
    hashPath.startsWith("/conversations");
  const hideNavigation = isConversationRoute;

  return (
    <>
      <ErrorBoundary FallbackComponent={Error}>
        <Suspense fallback={<Skeleton className="h-12 w-12 rounded-full" />}>
          <main
            id="main-content"
            className={cn("min-h-dvh", hideNavigation ? "" : "pb-24")}
          >
            {children}
          </main>
        </Suspense>
      </ErrorBoundary>
      {!hideNavigation && <MobileNavigation />}
      <Notification mobileOffset={{ bottom: hideNavigation ? "16px" : "72px" }} />
    </>
  );
};
