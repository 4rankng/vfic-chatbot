import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import {
  formatMetricDuration as fmtMs,
  formatStartedAt,
  getSlowTurnTone,
  likelyBottleneck,
} from "../../../reporting/domain/performanceDiagnostics";
import type { PerfSlowTurn } from "../../usePerformanceStats";
import { Status } from "../primitives";

/** Narrow-screen twin of the slow-turn table row, with its own detail stack. */
export const MobileTurnCard = ({ turn }: { turn: PerfSlowTurn }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [openDetail, setOpenDetail] = useState<string | null>(null);
  const tone = getSlowTurnTone(turn);
  const details = [
    {
      id: "pipeline",
      label: "Pipeline",
      value: `Hàng đợi ${turn.queue_depth ?? "—"} · Chờ slot ${fmtMs(turn.llm_queue_ms)}`,
    },
    {
      id: "llm",
      label: "LLM",
      value: `${turn.llm_calls ?? "—"} lượt · ${turn.tool_calls ?? "—"} tool · ${turn.model_tier ?? "Chưa có model"}`,
    },
    {
      id: "database",
      label: "Dữ liệu",
      value: `DB ${fmtMs(turn.db_ms)} · Tool ${fmtMs(turn.tool_ms)}`,
    },
    {
      id: "trace",
      label: "Trace",
      value: `${turn.conversation_id} · ${turn.intent ?? "Chưa có intent"}`,
    },
    {
      id: "tokens",
      label: "Tokens",
      value: `Prompt ${turn.prompt_tokens ?? "—"} · Completion ${turn.completion_tokens ?? "—"}`,
    },
  ];

  return (
    <article className={`is-${tone}`}>
      <div>
        <Status tone={tone}>
          {tone === "danger"
            ? "Cao"
            : tone === "warning"
              ? "Trung bình"
              : "Thấp"}
        </Status>
        <time>{formatStartedAt(turn.started_at)}</time>
      </div>
      <strong>{fmtMs(turn.total_ms)}</strong>
      <p>{likelyBottleneck(turn)}</p>
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((open) => !open)}
      >
        {isOpen ? "Thu gọn chi tiết" : "Xem chi tiết"}
        <ChevronRight aria-hidden="true" />
      </button>
      {isOpen ? (
        <div className="performance-mobile-turn-details">
          {details.map((detail) => (
            <section key={detail.id}>
              <button
                type="button"
                aria-expanded={openDetail === detail.id}
                onClick={() =>
                  setOpenDetail((current) =>
                    current === detail.id ? null : detail.id,
                  )
                }
              >
                <span>{detail.label}</span>
                <ChevronDown aria-hidden="true" />
              </button>
              {openDetail === detail.id ? <p>{detail.value}</p> : null}
            </section>
          ))}
        </div>
      ) : null}
    </article>
  );
};
