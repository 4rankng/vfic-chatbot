import { useNavigate } from "react-router-dom";
import { useTranslate } from "ra-core";
import { Activity, AlertCircle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

export const PerformanceLoading = () => (
  <div
    className="performance-skeletons"
    aria-label="Đang tải số liệu hiệu suất"
  >
    {Array.from({ length: 8 }, (_, index) => (
      <span key={index} className={index > 4 ? "is-panel" : undefined} />
    ))}
  </div>
);

export const PerformanceError = ({ onRetry }: { onRetry: () => void }) => {
  const navigate = useNavigate();
  const translate = useTranslate();
  return (
    <section
      className="performance-state tt-alert"
      role="status"
      aria-live="polite"
    >
      <AlertCircle aria-hidden="true" />
      <h2>{translate("performance.error_title")}</h2>
      <p>{translate("crm.common.retry_hint")}</p>
      <div>
        <Button onClick={onRetry}>
          <RefreshCw className="size-4" />
          {translate("crm.common.retry")}
        </Button>
        <Button variant="outline" onClick={() => navigate("/")}>
          {translate("crm.common.back_to_overview")}
        </Button>
      </div>
    </section>
  );
};

export const PerformanceNoActivity = ({
  windowLabel,
}: {
  windowLabel: string;
}) => (
  <section
    className="performance-no-activity"
    aria-labelledby="performance-no-activity-title"
  >
    <Activity aria-hidden="true" />
    <div>
      <h2 id="performance-no-activity-title">
        Chưa có lượt xử lý trong {windowLabel}
      </h2>
      <p>Trạng thái trực tiếp vẫn hiển thị phía trên.</p>
    </div>
  </section>
);
