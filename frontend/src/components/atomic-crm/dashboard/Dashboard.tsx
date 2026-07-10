import { InboxIcons } from "../conversations/InboxIcons";
import { RecruitingCommandCenter } from "./RecruitingCommandCenter";
import "./dashboard.css";

export const Dashboard = () => (
  <div className="dashboard-workspace">
    <InboxIcons />
    <section className="dashboard-workspace-content" aria-label="Tổng quan tuyển dụng">
      <RecruitingCommandCenter />
    </section>
  </div>
);
