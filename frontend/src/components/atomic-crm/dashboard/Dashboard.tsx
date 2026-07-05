import { lazy, Suspense } from "react";
import { InboxIcons } from "../conversations/InboxIcons";
import { WorkspaceIconRail } from "../conversations/WorkspaceShell";
import "../conversations/inbox.css";

const KnowledgeIngestPanel = lazy(() =>
  import("./KnowledgeIngestPanel").then((m) => ({
    default: m.KnowledgeIngestPanel,
  })),
);

export const Dashboard = () => (
  <div className="inbox-bg-container dashboard-workspace">
    <InboxIcons />
    <main className="app dashboard-app" id="app">
      <WorkspaceIconRail />
      <section className="panel center-panel dashboard-center-panel">
        <div className="dashboard-workspace-content">
          <Suspense fallback={null}>
            <KnowledgeIngestPanel variant="desktop" />
          </Suspense>
        </div>
      </section>
    </main>
  </div>
);
