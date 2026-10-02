import {
  AlertCircle,
  AlertTriangle,
  CheckCircle,
  ChevronRight,
  ClockCheck,
  CpuChip01,
  Send01,
} from "@untitledui/icons";

import type { PerfMetrics } from "../../usePerformanceStats";
import type { Icon } from "../primitives";
import { collectSignals, type SignalKind } from "../signals";

const SIGNAL_ICONS: Record<SignalKind, Icon> = {
  latency: ClockCheck,
  "rate-limit": AlertTriangle,
  failed: Send01,
  unknown: AlertCircle,
  capacity: CpuChip01,
  stable: CheckCircle,
};

/**
 * "Tín hiệu cần xử lý" — the one window that stays above the fold. It renders
 * the ranked signals from `collectSignals` with tone-chipped icons and a jump
 * to the slow-turn review table.
 */
export const AttentionQueue = ({ data }: { data: PerfMetrics }) => {
  const showRelatedTurns = () => {
    const target = document.getElementById("slow-turns");
    if (!target) return;
    target.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
      block: "start",
    });
    target.focus({ preventScroll: true });
  };
  const signals = collectSignals(data);
  return (
    <section className="performance-panel performance-attention-panel">
      <div className="performance-section-heading">
        <div>
          <h2>
            Tín hiệu cần xử lý{" "}
            <span>
              {signals.filter((signal) => signal.tone !== "success").length}
            </span>
          </h2>
          <p>Ưu tiên theo ảnh hưởng tới ứng viên.</p>
        </div>
      </div>
      <ul className="performance-signal-list">
        {signals.slice(0, 5).map((signal) => {
          const SignalIcon = SIGNAL_ICONS[signal.id];
          return (
            <li key={signal.id} className={`is-${signal.tone}`}>
              <span className="performance-signal-icon" aria-hidden="true">
                <SignalIcon />
              </span>
              <div>
                <strong>{signal.title}</strong>
                <small>{signal.detail}</small>
              </div>
              {signal.tone === "success" ? null : (
                <>
                  <b>{signal.value}</b>
                  {data.slow_turns.length > 0 ? (
                    <button
                      type="button"
                      aria-label={`Xem lượt liên quan đến ${signal.title}`}
                      onClick={showRelatedTurns}
                    >
                      <ChevronRight aria-hidden="true" />
                    </button>
                  ) : null}
                </>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
};
