import { formatMetricDuration as fmtMs } from "../../../reporting/domain/performanceDiagnostics";
import type { PerfSlowTurn } from "../../usePerformanceStats";

/** Expanded diagnostic breakdown for one slow turn. */
export const TurnDetail = ({ turn }: { turn: PerfSlowTurn }) => (
  <div className="performance-row-detail">
    <div>
      <strong>Điều phối</strong>
      <p>
        Hàng đợi: <code>{turn.queue_depth ?? "—"}</code> · Chờ slot:{" "}
        <code>{fmtMs(turn.llm_queue_ms)}</code>
      </p>
      <p>
        Độ trễ chưa phân bổ: <code>{fmtMs(turn.dark_time_ms)}</code>
      </p>
    </div>
    <div>
      <strong>LLM & tool</strong>
      <p>
        {turn.llm_calls ?? "—"} lượt LLM · {turn.tool_calls ?? "—"} lượt tool
      </p>
      <p>
        Model: <code>{turn.model_tier ?? "—"}</code>
        {turn.retried_429 ? " · Đã retry 429" : ""}
      </p>
    </div>
    <div>
      <strong>Dữ liệu & token</strong>
      <p>
        DB: <code>{fmtMs(turn.db_ms)}</code> · Tool:{" "}
        <code>{fmtMs(turn.tool_ms)}</code>
      </p>
      <p>
        Prompt: {turn.prompt_tokens ?? "—"} · Completion:{" "}
        {turn.completion_tokens ?? "—"}
      </p>
    </div>
    <div>
      <strong>Trace</strong>
      <p>
        <code>{turn.conversation_id}</code>
      </p>
      <p>Intent: {turn.intent ?? "Chưa có"}</p>
    </div>
  </div>
);
