import { InboxIcons } from "../conversations/InboxIcons";
import { WorkspaceIconRail } from "../conversations/WorkspaceShell";
import "../conversations/inbox.css";
import { RecruitingCommandCenter } from "./RecruitingCommandCenter";

export const Dashboard = () => (
  <div className="inbox-bg-container dashboard-workspace">
    <InboxIcons />
    <main className="app dashboard-app" id="app">
      <WorkspaceIconRail />
      <section className="panel center-panel dashboard-center-panel">
        <div className="dashboard-workspace-content">
          <RecruitingCommandCenter />
        </div>
      </section>
    </main>
  </div>
);
