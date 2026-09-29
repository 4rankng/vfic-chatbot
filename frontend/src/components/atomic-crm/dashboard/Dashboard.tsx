import { Wrench } from "lucide-react";

import { InboxIcons } from "../conversations/InboxIcons";
import { EmptyState } from "../kit";
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
      className="dashboard-workspace-content uu-scope"
      aria-label="Tổng quan"
    >
      {ATTENTION_DASHBOARD_ENABLED ? (
        <RecruitingCommandCenter />
      ) : (
        <div className="recruiting-command">
          <header className="recruiting-hero recruiting-hero-minimal">
            <div className="recruiting-hero-copy">
              <span className="recruiting-eyebrow">Theo dõi trực tiếp</span>
              <h1>Tổng quan</h1>
            </div>
          </header>
          <EmptyState
            icon={<Wrench className="size-6" aria-hidden="true" />}
            title="Bảng điều khiển đang tạm bảo trì"
            description="Vui lòng quay lại sau ít phút."
          />
        </div>
      )}
    </section>
  </div>
);
