import { describe, expect, it } from "vitest";

import {
  filterLeadCardRows,
  leadStageMeta,
  LEAD_STAGE_FILTERS,
  LEAD_SORT_LABELS,
  type LeadCardRow,
} from "./leadCardDirectory";

const row = (
  overrides: Partial<LeadCardRow> & Pick<LeadCardRow, "id">,
): LeadCardRow => ({
  name: `Ứng viên ${overrides.id}`,
  phone: "0912345678",
  desired_job: "Nhân viên kinh doanh",
  expected_salary: "12 triệu",
  lead_stage: "NEW",
  conversation_id: null,
  created_at: "2026-10-20T09:00:00+07:00",
  ...overrides,
});

const ROWS: LeadCardRow[] = [
  row({
    id: 1,
    name: "Nguyễn Thị Mai",
    lead_stage: "CONTACTING",
    desired_job: "Nhân viên kinh doanh",
    created_at: "2026-10-21T08:00:00+07:00",
  }),
  row({
    id: 2,
    name: "Trần Văn Hùng",
    lead_stage: "NEW",
    desired_job: "Kỹ sư vận hành",
    created_at: "2026-10-19T08:00:00+07:00",
  }),
  row({
    id: 3,
    name: "Lê Thị Hoa",
    lead_stage: "REGISTERED",
    desired_job: "Chăm sóc khách hàng",
    phone: "0903456789",
    created_at: "2026-10-17T08:00:00+07:00",
  }),
  row({
    id: 4,
    name: "Phạm Quốc Anh",
    lead_stage: "SKIPPED",
    desired_job: "Trưởng ca sản xuất",
    created_at: "2026-10-15T08:00:00+07:00",
  }),
];

describe("filterLeadCardRows", () => {
  it("defaults to newest-first over every stage", () => {
    const result = filterLeadCardRows(ROWS, {
      query: "",
      stage: "all",
      sort: "newest",
    });
    expect(result.map((r) => r.id)).toEqual([1, 2, 3, 4]);
  });

  it("sorts oldest-first and by Vietnamese name", () => {
    expect(
      filterLeadCardRows(ROWS, { query: "", stage: "all", sort: "oldest" }).map(
        (r) => r.id,
      ),
    ).toEqual([4, 3, 2, 1]);
    const byName = filterLeadCardRows(ROWS, {
      query: "",
      stage: "all",
      sort: "name",
    });
    expect(byName[0].name).toBe("Lê Thị Hoa");
  });

  it("filters by each stage chip", () => {
    expect(
      filterLeadCardRows(ROWS, {
        query: "",
        stage: "REGISTERED",
        sort: "newest",
      }).map((r) => r.id),
    ).toEqual([3]);
    expect(
      filterLeadCardRows(ROWS, {
        query: "",
        stage: "CONTACTING",
        sort: "newest",
      }).map((r) => r.id),
    ).toEqual([1]);
  });

  it("searches name, phone and desired job with Vietnamese diacritics", () => {
    expect(
      filterLeadCardRows(ROWS, {
        query: "hoa",
        stage: "all",
        sort: "newest",
      }).map((r) => r.id),
    ).toEqual([3]);
    expect(
      filterLeadCardRows(ROWS, {
        query: "0903456789",
        stage: "all",
        sort: "newest",
      }).map((r) => r.id),
    ).toEqual([3]);
    expect(
      filterLeadCardRows(ROWS, {
        query: "ky su van hanh",
        stage: "all",
        sort: "newest",
      }).map((r) => r.id),
    ).toEqual([2]);
  });

  it("combines the stage chip with the search box", () => {
    expect(
      filterLeadCardRows(ROWS, {
        query: "nhân viên",
        stage: "CONTACTING",
        sort: "newest",
      }).map((r) => r.id),
    ).toEqual([1]);
    expect(
      filterLeadCardRows(ROWS, {
        query: "nhân viên",
        stage: "REGISTERED",
        sort: "newest",
      }),
    ).toEqual([]);
  });

  it("does not mutate the input order", () => {
    const before = ROWS.map((r) => r.id);
    filterLeadCardRows(ROWS, { query: "", stage: "all", sort: "oldest" });
    expect(ROWS.map((r) => r.id)).toEqual(before);
  });
});

describe("lead stage chip and badge metadata", () => {
  it("offers all stages plus 'Tất cả' with canonical labels", () => {
    expect(LEAD_STAGE_FILTERS.map((f) => f.value)).toEqual([
      "all",
      "NEW",
      "CONTACTING",
      "REGISTERED",
      "SKIPPED",
    ]);
    expect(leadStageMeta("CONTACTING")).toEqual({
      label: "Đang liên hệ",
      badgeClass: "lead-card-badge--contacting",
    });
    expect(leadStageMeta("REGISTERED")).toEqual({
      label: "Đã đăng ký",
      badgeClass: "lead-card-badge--registered",
    });
  });

  it("maps unknown stages to the neutral badge and label", () => {
    expect(leadStageMeta("WHAT")).toEqual({
      label: "Chưa có giai đoạn",
      badgeClass: "lead-card-badge--unknown",
    });
    expect(leadStageMeta(null)).toEqual({
      label: "Chưa có giai đoạn",
      badgeClass: "lead-card-badge--unknown",
    });
  });

  it("labels every sort mode", () => {
    expect(LEAD_SORT_LABELS.newest).toBe("Mới nhất");
    expect(LEAD_SORT_LABELS.oldest).toBe("Cũ nhất");
    expect(LEAD_SORT_LABELS.name).toBe("Tên A–Z");
  });
});
