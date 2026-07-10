import type { ReactNode } from "react";
import { useIsMobile } from "@/hooks/use-mobile";
import { InboxIcons } from "../conversations/InboxIcons";
import "../conversations/inbox.css";

type PersonaWorkspaceShellProps = {
  children: ReactNode;
};

export const PersonaWorkspaceShell = ({
  children,
}: PersonaWorkspaceShellProps) => {
  const isMobile = useIsMobile();
  if (isMobile) return children;

  return (
    <div className="inbox-bg-container persona-workspace">
      <InboxIcons />
      <div className="app persona-app" id="app">
        <section className="panel center-panel persona-center-panel">
          {children}
        </section>
      </div>
    </div>
  );
};
