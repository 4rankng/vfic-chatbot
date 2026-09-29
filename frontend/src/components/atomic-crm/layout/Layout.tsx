import { Suspense, type ReactNode } from "react";
import { ErrorBoundary } from "react-error-boundary";
import { useLocation } from "react-router";
import { Notification } from "@/components/admin/notification";
import { Error } from "@/components/admin/error";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { WorkspaceShell } from "./workspace-shell";
import "../kit/tailkit-system.css";

export const Layout = ({ children }: { children: ReactNode }) => {
  const location = useLocation();
  const hashPath =
    typeof window === "undefined"
      ? ""
      : window.location.hash.replace(/^#/, "").split("?")[0];
  const isDashboardWorkspace =
    location.pathname === "/" && (hashPath === "" || hashPath === "/");
  const isConversationWorkspace =
    location.pathname.startsWith("/conversations") ||
    hashPath.startsWith("/conversations");
  const isKnowledgeWorkspace =
    location.pathname.startsWith("/knowledge_sources") ||
    hashPath.startsWith("/knowledge_sources");
  const isIntegrationWorkspace =
    location.pathname.startsWith("/settings") ||
    hashPath.startsWith("/settings") ||
    location.pathname.startsWith("/zalo_integrations") ||
    hashPath.startsWith("/zalo_integrations");
  const isPersonaWorkspace =
    location.pathname.startsWith("/personas") ||
    hashPath.startsWith("/personas");
  const isProjectWorkspace =
    location.pathname.startsWith("/projects") ||
    hashPath.startsWith("/projects");
  const isProfileWorkspace =
    location.pathname.startsWith("/profile") || hashPath.startsWith("/profile");
  const isPerformanceWorkspace = hashPath.startsWith("/hieu-suat");
  const isFullHeightWorkspace =
    isDashboardWorkspace ||
    isConversationWorkspace ||
    isKnowledgeWorkspace ||
    isIntegrationWorkspace ||
    isPersonaWorkspace ||
    isProjectWorkspace ||
    isProfileWorkspace ||
    isPerformanceWorkspace;

  return (
    <>
      <WorkspaceShell
        contentClassName={cn(
          "tailkit-workspace-content",
          isFullHeightWorkspace
            ? "md:h-full md:min-h-0 max-w-none md:overflow-hidden p-0"
            : "max-w-none overflow-y-auto p-0",
        )}
      >
        <ErrorBoundary FallbackComponent={Error}>
          <Suspense fallback={<Skeleton className="h-12 w-12 rounded-full" />}>
            {children}
          </Suspense>
        </ErrorBoundary>
      </WorkspaceShell>
      <Notification />
    </>
  );
};
