import { useMemo, useState } from "react";
import { ClockRefresh } from "@untitledui/icons";

import {
  ButtonGroup,
  ButtonGroupItem,
} from "@/components/base/button-group/button-group";
import { Button } from "@/components/base/buttons/button";
import { ProgressBarBase } from "@/components/base/progress-indicators/progress-indicators";
import { PerformanceResponseTimeChart } from "./PerformanceResponseTimeChart";
import { formatMilliseconds, formatPercent } from "./performanceFormat";
import { PerformanceError, PerformanceLoading } from "./pageStates";
import {
  type PerfMetrics,
  type PerfWindow,
  usePerformanceStats,
} from "./usePerformanceStats";
import "./performance.css";

const WINDOWS = [
  { key: "1d", label: "1 ngày" },
  { key: "7d", label: "7 ngày" },
  { key: "1m", label: "1 tháng" },
  { key: "3m", label: "3 tháng" },
  { key: "6m", label: "6 tháng" },
] as const;

/**
 * The two numbers the page exists for: how long the bot takes to answer, and
 * how often that conversation yielded a phone number. Everything else the old
 * dashboard carried (live tiles, stage matrix, adapter comparison, slow turns)
 * is gone.
 */
export const PerformanceMetrics = ({ data }: { data: PerfMetrics }) => {
  const { response_time: responseTime, conversion } = data;
  return (
    <>
      <section className="performance-panel">
        <h2>Thời gian phản hồi</h2>
        <p className="performance-panel-sub">p95 · mục tiêu ≤ 10 giây</p>
        <p className="performance-metric-value">
          {formatMilliseconds(responseTime.p95_ms)}
        </p>
        <p className="performance-panel-sub">
          p50 {formatMilliseconds(responseTime.p50_ms)}
        </p>
        <PerformanceResponseTimeChart
          trend={responseTime.trend}
          window={data.window}
        />
      </section>
      <section className="performance-panel">
        <h2>Tỷ lệ thu được số điện thoại</h2>
        <p className="performance-panel-sub">
          ứng viên nhắn tin và để lại số điện thoại
        </p>
        <p className="performance-metric-value">
          {formatPercent(conversion.rate_pct)}
        </p>
        <p className="performance-panel-sub">
          {conversion.with_phone.toLocaleString("vi-VN")} /{" "}
          {conversion.candidate_chats.toLocaleString("vi-VN")} cuộc trò chuyện
        </p>
        {conversion.candidate_chats > 0 ? (
          <ProgressBarBase
            className="uu-scope performance-conversion-meter"
            value={conversion.rate_pct ?? 0}
          />
        ) : (
          <p className="performance-empty">
            Chưa có cuộc trò chuyện nào từ ứng viên trong khoảng thời gian này.
          </p>
        )}
      </section>
    </>
  );
};

/** Page shell: period switcher, manual refresh, and the three load states. */
const PerformancePanel = () => {
  const [windowKey, setWindowKey] = useState<PerfWindow>("7d");
  const { data, isPending, isFetching, isError, refetch, dataUpdatedAt } =
    usePerformanceStats(windowKey);
  const freshness = useMemo(
    () =>
      dataUpdatedAt
        ? new Intl.DateTimeFormat("vi-VN", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          }).format(dataUpdatedAt)
        : null,
    [dataUpdatedAt],
  );
  const hasError = !data;
  const refreshing = Boolean(isPending || isFetching);
  return (
    <div className="performance-page" aria-busy={refreshing || undefined}>
      <header className="performance-header">
        <div>
          <h1>Hiệu suất chatbot</h1>
          <p>
            Thời gian phản hồi và tỷ lệ thu được số điện thoại theo khoảng thời
            gian.
          </p>
        </div>
        <div className="performance-header-actions">
          <ButtonGroup
            size="sm"
            className="performance-window-switcher uu-scope"
            aria-label="Khoảng thời gian"
            selectedKeys={[windowKey]}
            onSelectionChange={(keys) => {
              const next = [...keys][0];
              if (next) setWindowKey(next as PerfWindow);
            }}
          >
            {WINDOWS.map((window) => (
              <ButtonGroupItem
                key={window.key}
                id={window.key}
                className="performance-window-option"
              >
                {window.label}
              </ButtonGroupItem>
            ))}
          </ButtonGroup>
          <Button
            type="button"
            color="secondary"
            size="sm"
            className="performance-refresh"
            onClick={() => void refetch()}
            isDisabled={refreshing}
            aria-label={
              freshness ? `Cập nhật lúc ${freshness}` : "Cập nhật dữ liệu"
            }
            iconLeading={
              <ClockRefresh
                className={refreshing ? "is-spinning" : undefined}
                aria-hidden={true}
              />
            }
          >
            {freshness ? (
              <>
                <span className="performance-refresh-prefix">
                  Cập nhật lúc{" "}
                </span>
                {freshness}
              </>
            ) : (
              "Cập nhật"
            )}
          </Button>
        </div>
      </header>
      {data && isError ? (
        <div className="performance-stale-notice" role="alert">
          Chưa cập nhật được số liệu. Dữ liệu lần tải trước vẫn hiển thị; chọn
          Cập nhật để thử lại.
        </div>
      ) : null}
      {isPending ? <PerformanceLoading /> : null}
      {!isPending && hasError ? (
        <PerformanceError onRetry={() => void refetch()} />
      ) : null}
      {!isPending && !hasError && data ? (
        <PerformanceMetrics data={data} />
      ) : null}
    </div>
  );
};

export const PerformancePage = () => <PerformancePanel />;
