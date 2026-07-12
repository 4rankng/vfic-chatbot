import { InboxIcons } from "../conversations/InboxIcons";
import { RecruitingCommandCenter } from "./RecruitingCommandCenter";
import "./dashboard.css";

/**
 * Rollback gate (Red-team High 11 + plan.md Rollback).
 *
 * The attention composition is the single dashboard view; the legacy
 * client-side aggregation that preceded it was removed in Phase 2 (the backend
 * `/dashboard/attention` endpoint is now the authority). For a clean rollback
 * — flip this flag to `"false"` and remove the additive endpoint:
 *
 *   VITE_ATTENTION_DASHBOARD_ENABLED=false
 *
 * Defaults ON (any value other than the literal `"false"` keeps the attention
 * dashboard live, so an unset variable never disables the feature by
 * accident). When OFF, the dashboard surfaces a maintenance notice instead of
 * calling the removed endpoint, so the rest of the app keeps working while ops
 * rolls forward/back.
 */
const ATTENTION_DASHBOARD_ENABLED =
  import.meta.env.VITE_ATTENTION_DASHBOARD_ENABLED !== "false";

export const Dashboard = () => (
  <div className="dashboard-workspace">
    <InboxIcons />
    <section
      className="dashboard-workspace-content"
      aria-label="Tổng quan tuyển dụng"
    >
      {ATTENTION_DASHBOARD_ENABLED ? (
        <RecruitingCommandCenter />
      ) : (
        <div className="recruiting-command" role="status">
          <header className="recruiting-hero recruiting-hero-minimal">
            <div className="recruiting-hero-copy">
              <span className="recruiting-eyebrow">Theo dõi trực tiếp</span>
              <h1>Tổng quan tuyển dụng</h1>
              <p>
                Bảng điều khiển đang tạm bảo trì. Vui lòng quay lại sau ít phút.
              </p>
            </div>
          </header>
        </div>
      )}
    </section>
  </div>
);
