import { useDeferredValue, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { ArrowDown, ArrowUp, ArrowUpDown, Minus, Search } from "lucide-react";

import { ButtonUtility } from "@/components/base/buttons/button-utility";
import { Dropdown } from "@/components/base/dropdown/dropdown";
import type { DashboardCandidate } from "./candidateDashboard";
import {
  filterLeadCardRows,
  LEAD_SORT_LABELS,
  LEAD_STAGE_FILTERS,
  leadStageMeta,
  type LeadCardRow,
  type LeadSortMode,
  type LeadStageFilter,
} from "./leadCardDirectory";

/**
 * Phone (<640px) leads directory: sticky search-as-you-type, horizontally
 * scrolling stage chips beneath it and a sort control beside the search box.
 * Cards answer "ai · vị trí · kỳ vọng lương · giai đoạn" and open the
 * conversation record — the same destination as the desktop rows. The desktop
 * keeps its existing day-grouped rows; the panel swaps to this surface only
 * below 640px.
 */
export const LeadCardList = ({
  candidates,
}: {
  candidates: readonly DashboardCandidate[];
}) => {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState<LeadStageFilter>("all");
  const [sort, setSort] = useState<LeadSortMode>("newest");
  // Defer the filtering query so fast typing never blocks the input.
  const deferredQuery = useDeferredValue(query);

  const rows = useMemo<LeadCardRow[]>(
    () =>
      candidates.map((candidate) => ({
        id: candidate.id,
        name: candidate.name ?? candidate.lead?.name ?? null,
        phone: candidate.phone ?? candidate.lead?.phone ?? null,
        desired_job: candidate.lead?.desired_job ?? null,
        expected_salary: candidate.lead?.expected_salary ?? null,
        lead_stage: candidate.lead?.lead_stage ?? null,
        conversation_id: candidate.conversation_id,
        created_at: candidate.created_at,
      })),
    [candidates],
  );
  const visible = useMemo(
    () => filterLeadCardRows(rows, { query: deferredQuery, stage, sort }),
    [rows, deferredQuery, stage, sort],
  );

  return (
    <div className="lead-card-directory">
      <div className="lead-card-toolbar">
        <div className="lead-card-toolbar-row">
          <label className="lead-card-search">
            <Search className="lead-card-search-icon" aria-hidden="true" />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Tìm tên, số điện thoại, vị trí…"
              aria-label="Tìm ứng viên"
            />
          </label>
          <Dropdown.Root>
            <ButtonUtility
              color="tertiary"
              tooltip={`Sắp xếp: ${LEAD_SORT_LABELS[sort]}`}
              className="uu-scope lead-card-sort"
              icon={<ArrowUpDown aria-hidden="true" />}
            />
            <Dropdown.Popover placement="bottom end" offset={8}>
              <Dropdown.Menu>
                {(Object.keys(LEAD_SORT_LABELS) as LeadSortMode[]).map(
                  (mode) => (
                    <Dropdown.Item
                      key={mode}
                      id={`sort-${mode}`}
                      className="lead-card-sort-item"
                      label={LEAD_SORT_LABELS[mode]}
                      icon={
                        mode === "newest"
                          ? ArrowDown
                          : mode === "oldest"
                            ? ArrowUp
                            : Minus
                      }
                      onPress={() => setSort(mode)}
                    />
                  ),
                )}
              </Dropdown.Menu>
            </Dropdown.Popover>
          </Dropdown.Root>
        </div>
        <div
          className="lead-card-chips"
          role="group"
          aria-label="Lọc theo giai đoạn"
        >
          {LEAD_STAGE_FILTERS.map((filter) => (
            <button
              key={filter.value}
              type="button"
              className={`lead-chip${stage === filter.value ? " is-active" : ""}`}
              aria-pressed={stage === filter.value}
              onClick={() => setStage(filter.value)}
            >
              {filter.label}
            </button>
          ))}
        </div>
      </div>

      {visible.length === 0 ? (
        <p className="lead-card-empty" role="status">
          Không tìm thấy ứng viên phù hợp.
        </p>
      ) : (
        <ul className="lead-card-list">
          {visible.map((row) => {
            const meta = leadStageMeta(row.lead_stage);
            const name = row.name ?? "Ứng viên";
            const content = (
              <>
                <span className="lead-card-main">
                  <span className="lead-card-title">{name}</span>
                  <span className="lead-card-subtitle">
                    {row.desired_job ?? "Chưa có vị trí mong muốn"}
                  </span>
                  <span className={`lead-card-badge ${meta.badgeClass}`}>
                    {meta.label}
                  </span>
                </span>
                <span className="lead-card-value">
                  {row.expected_salary ?? "—"}
                </span>
              </>
            );
            return (
              <li key={row.id}>
                {row.conversation_id ? (
                  <button
                    type="button"
                    data-allow-tall
                    className="lead-card"
                    aria-label={`Mở hội thoại với ${name}`}
                    onClick={() =>
                      navigate(`/conversations?id=${row.conversation_id}`)
                    }
                  >
                    {content}
                  </button>
                ) : (
                  <div className="lead-card is-static" aria-label={name}>
                    {content}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};
