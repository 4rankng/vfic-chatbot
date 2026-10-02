import { createRef } from "react";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

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

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 900);
});

describe("CandidateDataDialog", () => {
  it.each([320, 390, 1280])(
    "keeps the portal form compact on a mouse-operated viewport at %ipx",
    async (width) => {
      await page.viewport(width, 844);
      expect(window.matchMedia("(pointer: fine)").matches).toBe(true);
      const screen = await render(
        <TestMessages>
          <CandidateDataDialog
            lead={lead}
            displayName="Bùi Hải Anh"
            open
            onOpenChange={vi.fn()}
            returnFocusRef={createRef<HTMLButtonElement>()}
            canEdit
            onSave={vi.fn()}
          />
        </TestMessages>,
      );
      await screen.getByRole("button", { name: "Chỉnh sửa" }).click();
      const dialog = screen
        .getByRole("dialog", { name: "Thông tin ứng viên" })
        .element();
      const inputs = dialog.querySelectorAll<HTMLInputElement>("input");
      expect(inputs.length).toBeGreaterThan(3);
      for (const input of inputs) {
        const box = input.closest<HTMLElement>('[class~="group/input"]')!;
        expect(box.getBoundingClientRect().height).toBe(width < 768 ? 40 : 36);
        expect(getComputedStyle(input).fontSize).toBe("12px");
        expect(input.getBoundingClientRect().height).toBeLessThanOrEqual(
          box.getBoundingClientRect().height,
        );
      }
      const form = dialog.querySelector<HTMLElement>(".candidate-data-form")!;
      expect(getComputedStyle(form).gap).toBe("12px");
      expect(
        screen
          .getByRole("button", { name: "Lưu thay đổi" })
          .element()
          .getBoundingClientRect().height,
      ).toBe(width < 768 ? 40 : 36);
    },
  );
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
    expect(
      Array.from(
        document.querySelectorAll<HTMLInputElement>("[role=dialog] input"),
      )
        .map((input) => input.name)
        .slice(0, 4),
    ).toEqual(["phone", "name", "desired_job", "birth_year"]);
    await expect
      .element(screen.getByLabelText("Số điện thoại"))
      .toHaveAttribute("type", "tel");
    await expect
      .element(screen.getByLabelText("Số điện thoại"))
      .toHaveAttribute("autocomplete", "tel");
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
    await expect
      .element(screen.getByText(/Đã có số điện thoại để liên hệ/))
      .toBeVisible();
  });
});
