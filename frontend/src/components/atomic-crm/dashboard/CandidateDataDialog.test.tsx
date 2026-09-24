import { createRef } from "react";
import { render } from "vitest-browser-react";
import { describe, expect, it, vi } from "vitest";

import type { Lead } from "../types";
import { CandidateDataDialog } from "./CandidateDataDialog";
import "@/index.css";
import { TestMessages } from "@/components/atomic-crm/providers/commons/TestMessages";

const lead: Lead = {
  id: 42,
  zalo_id: "oa:user-42",
  name: "Bùi Hải Anh",
  phone: "0962548483",
  desired_job: "",
  expected_salary: "10 triệu",
  lead_score: null,
  lead_stage: "",
  version: 3,
  created_at: "2026-07-14T08:30:00Z",
  updated_at: "2026-07-14T08:30:00Z",
};

describe("CandidateDataDialog", () => {
  it("keeps the form open and shows a save error after a conflicting update", async () => {
    const onSave = vi
      .fn()
      .mockRejectedValue(new Error("Vừa được nhân viên khác thay đổi"));
    const screen = await render(
      <TestMessages>
        <CandidateDataDialog
          lead={lead}
          displayName="Bùi Hải Anh"
          open
          onOpenChange={vi.fn()}
          returnFocusRef={createRef<HTMLButtonElement>()}
          canEdit
          onSave={onSave}
        />
      </TestMessages>,
    );

    await screen.getByRole("button", { name: "Chỉnh sửa" }).click();
    await screen
      .getByLabelText("Công việc mong muốn")
      .fill("Công nhân sản xuất");
    await screen.getByRole("button", { name: "Lưu thay đổi" }).click();

    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent("Vừa được nhân viên khác thay đổi");
    await expect
      .element(screen.getByLabelText("Công việc mong muốn"))
      .toHaveValue("Công nhân sản xuất");
    expect(onSave).toHaveBeenCalledWith(
      { desired_job: "Công nhân sản xuất" },
      3,
    );
  });

  it("does not expose editing controls to a read-only user", async () => {
    const screen = await render(
      <TestMessages>
        <CandidateDataDialog
          lead={lead}
          displayName="Bùi Hải Anh"
          open
          onOpenChange={vi.fn()}
          returnFocusRef={createRef<HTMLButtonElement>()}
          canEdit={false}
          onSave={vi.fn()}
        />
      </TestMessages>,
    );

    await expect
      .element(screen.getByRole("button", { name: "Chỉnh sửa" }))
      .not.toBeInTheDocument();
    await expect.element(screen.getByText("Dữ liệu đã thu thập")).toBeVisible();
  });
});
