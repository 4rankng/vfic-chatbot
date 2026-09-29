import { useNavigate } from "react-router-dom";
import { useTranslate } from "ra-core";
import { Activity, AlertCircle, RefreshCw } from "lucide-react";

import { LoadingIndicator } from "@/components/application/loading-indicator/loading-indicator";
import { Button } from "@/components/base/buttons/button";
import { EmptyState } from "../../kit";

/**
 * The dashboard's three load states, on Untitled UI anatomy.
 *
 * Loading is the library's `LoadingIndicator` inside a `role="status"` region —
 * the console has no loading primitive of its own. The error and no-activity
 * states are the shared kit `EmptyState`, the same frame every other console
 * screen routes its empty and failed states through (see
 * `conversations/presentation/ConversationList`), so the icon frame, the type
 * scale and the action placement move together.
 */
export const PerformanceLoading = () => (
  <div
    role="status"
    aria-label="Đang tải số liệu hiệu suất"
    className="uu-scope flex justify-center py-10"
  >
    <LoadingIndicator
      type="line-spinner"
      size="md"
      label="Đang tải số liệu hiệu suất"
    />
  </div>
);

export const PerformanceError = ({ onRetry }: { onRetry: () => void }) => {
  const navigate = useNavigate();
  const translate = useTranslate();
  return (
    <div role="status" aria-live="polite">
      <EmptyState
        icon={<AlertCircle className="size-6" aria-hidden="true" />}
        title={translate("performance.error_title")}
        description={translate("crm.common.retry_hint")}
        action={
          <>
            <Button
              color="primary"
              iconLeading={<RefreshCw />}
              onClick={onRetry}
            >
              {translate("crm.common.retry")}
            </Button>
            <Button color="secondary" onClick={() => navigate("/")}>
              {translate("crm.common.back_to_overview")}
            </Button>
          </>
        }
      />
    </div>
  );
};

export const PerformanceNoActivity = ({
  windowLabel,
}: {
  windowLabel: string;
}) => (
  <EmptyState
    icon={<Activity className="size-6" aria-hidden="true" />}
    title={`Chưa có lượt xử lý trong ${windowLabel}`}
    description="Trạng thái trực tiếp vẫn hiển thị phía trên."
  />
);
