import { cleanup, render } from "vitest-browser-react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { LeadCardList } from "./LeadCardList";
import type { DashboardCandidate } from "./candidateDashboard";

const candidate = (
  overrides: Partial<DashboardCandidate> & Pick<DashboardCandidate, "id">,
): DashboardCandidate => ({
  zalo_id: `z-${overrides.id}`,
  name: `Ứng viên ${overrides.id}`,
  phone: "0912345678",
  avatar_url: null,
  conversation_id: `c-${overrides.id}`,
  created_at: "2026-10-20T09:00:00+07:00",
  lead: {
    id: overrides.id,
    zalo_id: `z-${overrides.id}`,
    name: `Ứng viên ${overrides.id}`,
    phone: "0912345678",
    desired_job: "Nhân viên kinh doanh",
    expected_salary: "12 triệu",
    lead_score: null,
    lead_stage: "NEW",
    created_at: "2026-10-20T09:00:00+07:00",
    updated_at: "2026-10-20T09:00:00+07:00",
  },
  ...overrides,
});

const CANDIDATES: DashboardCandidate[] = [
  candidate({
    id: 1,
    name: "Nguyễn Thị Mai",
    conversation_id: "c-1",
    created_at: "2026-10-21T08:00:00+07:00",
    lead: {
      id: 1,
      zalo_id: "z-1",
      name: "Nguyễn Thị Mai",
      phone: "0912345678",
      desired_job: "Nhân viên kinh doanh",
      expected_salary: "12–15 triệu",
      lead_score: "hot",
      lead_stage: "CONTACTING",
      created_at: "2026-10-21T08:00:00+07:00",
      updated_at: "2026-10-21T08:00:00+07:00",
    },
  }),
  candidate({
    id: 2,
    name: "Trần Văn Hùng",
    conversation_id: "c-2",
    created_at: "2026-10-19T08:00:00+07:00",
    lead: {
      id: 2,
      zalo_id: "z-2",
      name: "Trần Văn Hùng",
      phone: "0987654321",
      desired_job: "Kỹ sư vận hành",
      expected_salary: "18 triệu",
      lead_score: "warm",
      lead_stage: "NEW",
      created_at: "2026-10-19T08:00:00+07:00",
      updated_at: "2026-10-19T08:00:00+07:00",
    },
  }),
  candidate({
    id: 3,
    name: "Lê Thị Hoa",
    conversation_id: "c-3",
    created_at: "2026-10-17T08:00:00+07:00",
    lead: {
      id: 3,
      zalo_id: "z-3",
      name: "Lê Thị Hoa",
      phone: "0903456789",
      desired_job: "Chăm sóc khách hàng",
      expected_salary: "10 triệu",
      lead_score: null,
      lead_stage: "REGISTERED",
      created_at: "2026-10-17T08:00:00+07:00",
      updated_at: "2026-10-17T08:00:00+07:00",
    },
  }),
];

const LocationProbe = () => {
  const location = useLocation();
  return (
    <output data-testid="lead-location">
      {location.pathname}
      {location.search}
    </output>
  );
};

const renderList = async () =>
  render(
    <MemoryRouter>
      <LeadCardList candidates={CANDIDATES} />
      <LocationProbe />
    </MemoryRouter>,
  );

describe("LeadCardList", () => {
  afterEach(async () => {
    await cleanup();
  });

  it("renders name · desired job · expected salary · stage badge per card", async () => {
    const screen = await renderList();

    await expect
      .element(
        screen.getByRole("button", { name: "Mở hội thoại với Nguyễn Thị Mai" }),
      )
      .toBeVisible();
    await expect
      .element(screen.getByText("Nhân viên kinh doanh"))
      .toBeVisible();
    await expect.element(screen.getByText("12–15 triệu")).toBeVisible();
    // Stage badges share their text with the filter chips, so they are
    // asserted inline within the card content instead of by standalone text.
    await expect
      .element(screen.getByRole("list"))
      .toHaveTextContent(
        /Nguyễn Thị Mai\s*Nhân viên kinh doanh\s*Đang liên hệ\s*12–15 triệu/,
      );
    await expect
      .element(screen.getByRole("list"))
      .toHaveTextContent(
        /Lê Thị Hoa\s*Chăm sóc khách hàng\s*Đã đăng ký\s*10 triệu/,
      );
  });

  it("defaults to newest-first order", async () => {
    const screen = await renderList();

    await expect
      .element(screen.getByRole("list"))
      .toHaveTextContent(/Nguyễn Thị Mai[\s\S]*Trần Văn Hùng[\s\S]*Lê Thị Hoa/);
  });

  it("opens the conversation record when a card is tapped", async () => {
    const screen = await renderList();

    await screen
      .getByRole("button", { name: "Mở hội thoại với Nguyễn Thị Mai" })
      .click();
    await expect
      .element(screen.getByTestId("lead-location"))
      .toHaveTextContent("/conversations?id=c-1");
  });

  it("filters the cards with the stage chips", async () => {
    const screen = await renderList();

    await screen.getByRole("button", { name: "Đã đăng ký" }).click();
    await expect.element(screen.getByText("Lê Thị Hoa")).toBeVisible();
    await expect
      .element(screen.getByText("Nguyễn Thị Mai"))
      .not.toBeInTheDocument();
    await expect
      .element(screen.getByText("Trần Văn Hùng"))
      .not.toBeInTheDocument();
  });

  it("filters the cards with the sticky search box", async () => {
    const screen = await renderList();

    await screen.getByLabelText("Tìm ứng viên").fill("ky su van hanh");
    await expect.element(screen.getByText("Trần Văn Hùng")).toBeVisible();
    await expect
      .element(screen.getByText("Nguyễn Thị Mai"))
      .not.toBeInTheDocument();
  });

  it("reverses the order from the sort control", async () => {
    const screen = await renderList();

    await screen.getByRole("button", { name: "Sắp xếp: Mới nhất" }).click();
    await screen.getByRole("menuitem", { name: "Cũ nhất" }).click();
    await expect
      .element(screen.getByRole("list"))
      .toHaveTextContent(/Lê Thị Hoa[\s\S]*Trần Văn Hùng[\s\S]*Nguyễn Thị Mai/);
    await expect
      .element(screen.getByRole("button", { name: "Sắp xếp: Cũ nhất" }))
      .toBeVisible();
  });

  it("shows an empty note when no card matches", async () => {
    const screen = await renderList();

    await screen.getByLabelText("Tìm ứng viên").fill("không tồn tại");
    await expect
      .element(screen.getByText("Không tìm thấy ứng viên phù hợp"))
      .toBeVisible();
  });
});
