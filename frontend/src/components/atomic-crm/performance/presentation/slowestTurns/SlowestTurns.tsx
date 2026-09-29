import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Button } from "@/components/base/buttons/button";
import { ButtonUtility } from "@/components/base/buttons/button-utility";

import {
  LANE_LABELS,
  OUTCOME_LABELS,
  formatMetricDuration as fmtMs,
  formatStartedAt,
  getSlowTurnTone,
  likelyBottleneck,
} from "../../../reporting/domain/performanceDiagnostics";
import type { PerfSlowTurn } from "../../usePerformanceStats";
import { Status } from "../primitives";
import { MobileTurnCard } from "./MobileTurnCard";
import { TurnDetail } from "./TurnDetail";

/**
 * "Lượt cần xem" — the ranked slow-turn list. The first eight rows render by
 * default; the rest stay behind an explicit "see more" toggle.
 */
export const SlowestTurns = ({ slowTurns }: { slowTurns: PerfSlowTurn[] }) => {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(false);
  const visibleTurns = showAll ? slowTurns : slowTurns.slice(0, 8);
  const hiddenCount = slowTurns.length - visibleTurns.length;
  return (
    <section
      className="performance-panel performance-slow-turns tt-card tt-card-border"
      id="slow-turns"
    >
      <div className="performance-section-heading">
        <div>
          <h2>
            Lượt cần xem <span>{slowTurns.length}</span>
          </h2>
          <p>Các lượt ảnh hưởng tới phản hồi hoặc giao gửi.</p>
        </div>
      </div>
      {slowTurns.length === 0 ? (
        <p className="performance-empty">
          Chưa có lượt cần xem trong khoảng này.
        </p>
      ) : (
        <>
          <div
            className="performance-table-wrap"
            role="region"
            aria-label="Bảng lượt cần xem"
            tabIndex={0}
          >
            <table className="tt-table tt-table-sm">
              <thead>
                <tr>
                  <th>Mức độ</th>
                  <th>Thời gian</th>
                  <th>Tổng</th>
                  <th>Nút thắt nhiều khả năng</th>
                  <th>Luồng</th>
                  <th>Kết quả giao gửi</th>
                  <th aria-label="Mở rộng" />
                </tr>
              </thead>
              <tbody>
                {visibleTurns.map((turn) => {
                  const tone = getSlowTurnTone(turn);
                  const isOpen = expandedId === turn.id;
                  return (
                    <Fragment key={turn.id}>
                      <tr className={isOpen ? "is-open" : undefined}>
                        <td>
                          <Status tone={tone}>
                            {tone === "danger"
                              ? "Cao"
                              : tone === "warning"
                                ? "Trung bình"
                                : "Thấp"}
                          </Status>
                        </td>
                        <td>{formatStartedAt(turn.started_at)}</td>
                        <td>
                          <b>{fmtMs(turn.total_ms)}</b>
                        </td>
                        <td>{likelyBottleneck(turn)}</td>
                        <td>
                          {LANE_LABELS[turn.lane ?? ""] ??
                            turn.lane ??
                            "Không rõ"}
                        </td>
                        <td>
                          <Status
                            tone={
                              turn.outcome === "ERROR" ? "danger" : "success"
                            }
                          >
                            {OUTCOME_LABELS[turn.outcome] ??
                              turn.outcome ??
                              "Không rõ"}
                          </Status>
                        </td>
                        <td>
                          <ButtonUtility
                            tooltip={
                              isOpen ? "Thu gọn chi tiết" : "Mở rộng chi tiết"
                            }
                            size="xs"
                            color="tertiary"
                            className="performance-expand"
                            aria-expanded={isOpen}
                            onClick={() =>
                              setExpandedId(isOpen ? null : turn.id)
                            }
                            icon={
                              isOpen ? (
                                <ChevronDown
                                  className="size-4"
                                  aria-hidden="true"
                                />
                              ) : (
                                <ChevronRight
                                  className="size-4"
                                  aria-hidden="true"
                                />
                              )
                            }
                          />
                        </td>
                      </tr>
                      {isOpen ? (
                        <tr className="performance-detail-row">
                          <td colSpan={7}>
                            <TurnDetail turn={turn} />
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="performance-turn-cards">
            {visibleTurns.map((turn) => (
              <MobileTurnCard key={turn.id} turn={turn} />
            ))}
          </div>
          {slowTurns.length > 8 ? (
            <Button
              type="button"
              color="tertiary"
              size="sm"
              className="performance-show-more"
              iconTrailing={
                <ChevronDown
                  className={showAll ? "is-open size-4" : "size-4"}
                  aria-hidden="true"
                />
              }
              onClick={() => {
                setShowAll((current) => !current);
                setExpandedId(null);
              }}
            >
              {showAll ? "Thu gọn" : `Xem thêm ${hiddenCount} lượt`}
            </Button>
          ) : null}
        </>
      )}
    </section>
  );
};
