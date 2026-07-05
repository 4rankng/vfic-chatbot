import type { ReactNode } from "react";
import { useIsMobile } from "@/hooks/use-mobile";
import { InboxIcons } from "../conversations/InboxIcons";
import { WorkspaceIconRail } from "../conversations/WorkspaceShell";
import "../conversations/inbox.css";

type ProjectWorkspaceShellProps = {
  children: ReactNode;
};

export const ProjectWorkspaceShell = ({
  children,
}: ProjectWorkspaceShellProps) => {
  const isMobile = useIsMobile();
  if (isMobile) return children;

  return (
    <div className="inbox-bg-container project-workspace">
      <InboxIcons />
      <main className="app project-app" id="app">
        <WorkspaceIconRail />
        <section className="panel center-panel project-center-panel">
          {children}
        </section>
      </main>
    </div>
  );
};
