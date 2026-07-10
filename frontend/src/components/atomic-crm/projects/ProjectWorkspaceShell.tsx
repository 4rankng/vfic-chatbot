import type { ReactNode } from "react";
import { useIsMobile } from "@/hooks/use-mobile";
import { InboxIcons } from "../conversations/InboxIcons";
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
      <div className="app project-app" id="app">
        <section className="panel center-panel project-center-panel">
          {children}
        </section>
      </div>
    </div>
  );
};
