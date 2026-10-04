import type { ReactNode } from "react";

/**
 * The one action row of the knowledge workspace: row-leading project controls
 * on the left, knowledge imports/exports on the right. Pure layout — the
 * panel owns the controls and their semantics.
 */
export const WorkspaceCommandBar = ({
  leading,
  trailing,
}: {
  leading?: ReactNode;
  trailing?: ReactNode;
}) => {
  if (!leading && !trailing) return null;
  return (
    <div className="project-workspace-command-bar">
      {leading ? (
        <div className="project-workspace-command-leading">{leading}</div>
      ) : null}
      {trailing ? (
        <div className="project-workspace-command-trailing">{trailing}</div>
      ) : null}
    </div>
  );
};
