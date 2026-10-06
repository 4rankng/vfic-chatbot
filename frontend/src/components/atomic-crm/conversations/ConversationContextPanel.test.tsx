import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, beforeEach, vi } from "vitest";
import type { Lead } from "../types";
import { ConversationContextPanel } from "./ConversationContextPanel";
import { TestMessages } from "@/components/atomic-crm/providers/commons/TestMessages";
import "@/index.css";
import "./inbox.css";

const mobileMock = vi.hoisted(() => ({ isMobile: false }));
vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: () => mobileMock.isMobile,
}));

// The panel reads the candidate's project interests per lead; every test that
// does not care about them gets an empty list (no row), never a real request.
const apiJsonMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/apiClient", () => ({ apiJson: apiJsonMock }));

beforeEach(() => {
  apiJsonMock.mockReset();
  apiJsonMock.mockResolvedValue([]);
});

afterEach(async () => {
  await cleanup();
  mobileMock.isMobile = false;
  await page.viewport(1280, 720);
});

const lead: Lead = {
  id: 1,
  version: 1,
  zalo_id: "candidate-1",
  name: "Ứng viên mẫu",
  phone: "",
  desired_job: "",
  expected_salary: "",
  lead_score: null,
  lead_stage: "NEW",
  created_at: "2026-07-15T00:00:00Z",
  updated_at: "2026-07-15T00:00:00Z",
  notes: "Không có kinh nghiệm\nHỏi về bảo hiểm tại LG Display",
};

describe("ConversationContextPanel notes", () => {
  it.each([320, 360, 390])(
    "uses the full %ipx phone width without framing icons or clipping edit fields",
    async (width) => {
      mobileMock.isMobile = true;
      await page.viewport(width, 740);
      const screen = await render(
        <TestMessages>
          <ConversationContextPanel
            lead={{
              ...lead,
              name: "Nguyễn Thị Thu Hương với tên ứng viên dài",
              desired_job: "Công nhân đóng gói tại dự án ở Hải Phòng",
            }}
            open
            canEdit
            onSave={vi.fn()}
            onClose={() => undefined}
          />
        </TestMessages>,
      );
      const dialog = screen.getByRole("dialog", { name: "Thông tin ứng viên" });
      await expect.element(dialog).toBeVisible();
      await expect
        .poll(() => Math.round(dialog.element().getBoundingClientRect().left))
        .toBe(0);
      expect(dialog.element().getBoundingClientRect().right).toBe(width);
      expect(dialog.element().scrollWidth).toBeLessThanOrEqual(width);
      // These phone values also prove the safe-area rule wins over the later
      // base header shorthand (18px); desktop context spacing stays separate.
      const header = dialog.element().querySelector(".profile-header")!;
      expect(getComputedStyle(header).paddingLeft).toBe("16px");
      expect(getComputedStyle(header).paddingRight).toBe("16px");
      for (const icon of dialog
        .element()
        .querySelectorAll(".candidate-info-icon, .context-close")) {
        const style = getComputedStyle(icon);
        expect(style.borderTopWidth).toBe("0px");
        expect(style.backgroundColor).toBe("rgba(0, 0, 0, 0)");
        expect(style.boxShadow).toBe("none");
      }
      await screen
        .getByRole("button", { name: "Chỉnh sửa hồ sơ ứng viên" })
        .click();
      await expect
        .element(screen.getByLabelText("Số điện thoại"))
        .toHaveFocus();
      for (const control of dialog
        .element()
        .querySelectorAll("input, textarea, button")) {
        const bounds = control.getBoundingClientRect();
        expect(bounds.left).toBeGreaterThanOrEqual(0);
        expect(bounds.right).toBeLessThanOrEqual(width);
      }
      expect(dialog.element().scrollWidth).toBeLessThanOrEqual(width);
    },
  );

  it("keeps phone fields compact while preserving larger bare icon targets", async () => {
    mobileMock.isMobile = true;
    await page.viewport(390, 844);
    const onSave = vi.fn().mockResolvedValue(undefined);
    const screen = await render(
      <TestMessages>
        <ConversationContextPanel
          lead={lead}
          open
          canEdit
          onSave={onSave}
          onClose={() => undefined}
        />
      </TestMessages>,
    );
    const dialog = screen.getByRole("dialog", { name: "Thông tin ứng viên" });
    await expect.element(dialog).toBeVisible();
    await screen
      .getByRole("button", { name: "Chỉnh sửa hồ sơ ứng viên" })
      .click();
    const inputs = dialog
      .element()
      .querySelectorAll<HTMLInputElement>('input[id^="candidate-profile-"]');
    expect(inputs.length).toBeGreaterThanOrEqual(4);
    for (const input of inputs) {
      const fieldHeight = input.parentElement!.getBoundingClientRect().height;
      expect(fieldHeight).toBe(40);
      expect(input.getBoundingClientRect().height).toBeLessThanOrEqual(
        fieldHeight,
      );
      expect(input.getBoundingClientRect().height).toBeGreaterThanOrEqual(36);
      expect(getComputedStyle(input).fontSize).toBe(
        window.matchMedia("(pointer: coarse)").matches ? "16px" : "12px",
      );
    }
    for (const name of ["Hủy", "Lưu thay đổi"]) {
      const action = screen.getByRole("button", { name }).element();
      expect(action.getBoundingClientRect().height).toBe(40);
    }
    expect(
      screen
        .getByRole("button", { name: "Đóng thông tin ứng viên" })
        .element()
        .getBoundingClientRect().height,
    ).toBeGreaterThanOrEqual(44);
    expect(onSave).not.toHaveBeenCalled();
  });
  it("keeps a mobile profile save open until its write finishes", async () => {
    mobileMock.isMobile = true;
    const onClose = vi.fn();
    let finish!: () => void;
    const onSave = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const screen = await render(
      <TestMessages>
        <ConversationContextPanel
          lead={lead}
          open
          canEdit
          onSave={onSave}
          onClose={onClose}
        />
      </TestMessages>,
    );
    await screen
      .getByRole("button", { name: "Chỉnh sửa hồ sơ ứng viên" })
      .click();
    await screen.getByLabelText("Họ tên").fill("Tên đang lưu");
    await screen.getByRole("button", { name: "Lưu thay đổi" }).click();
    await expect.poll(() => onSave.mock.calls.length).toBe(1);
    await expect
      .element(screen.getByRole("button", { name: "Đóng thông tin ứng viên" }))
      .toBeDisabled();
    expect(onClose).not.toHaveBeenCalled();
    finish();
    await expect
      .element(screen.getByRole("button", { name: "Đóng thông tin ứng viên" }))
      .not.toBeDisabled();
  });

  it("keeps a failed profile edit visible with an inline retry explanation", async () => {
    const screen = await render(
      <TestMessages>
        <ConversationContextPanel
          lead={lead}
          open
          persistent
          canEdit
          onSave={vi
            .fn()
            .mockRejectedValue(
              new Error("Hồ sơ vừa được cập nhật. Vui lòng tải lại."),
            )}
          onClose={() => undefined}
        />
      </TestMessages>,
    );
    await screen
      .getByRole("button", { name: "Chỉnh sửa hồ sơ ứng viên" })
      .click();
    await screen.getByLabelText("Họ tên").fill("Tên chưa lưu");
    await screen.getByRole("button", { name: "Lưu thay đổi" }).click();
    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent("Hồ sơ vừa được cập nhật. Vui lòng tải lại.");
    await expect
      .element(screen.getByLabelText("Họ tên"))
      .toHaveValue("Tên chưa lưu");
  });

  it("renders stored note lines as a semantic bullet list", async () => {
    const screen = await render(
      <TestMessages>
        <div className="inbox-bg-container">
          <ConversationContextPanel
            lead={lead}
            open
            persistent
            onClose={() => undefined}
          />
        </div>
      </TestMessages>,
    );

    await expect
      .element(screen.getByText(/Cần bổ sung số điện thoại để liên hệ/))
      .toBeVisible();
    await expect
      .element(screen.getByText(/Họ tên được khuyến khích/))
      .toBeVisible();
    const priorityFields = screen.container.querySelector(
      ".candidate-priority-fields",
    )!;
    expect(
      Array.from(priorityFields.querySelectorAll("[data-field]")).map((item) =>
        item.getAttribute("data-field"),
      ),
    ).toEqual(["phone", "name", "expectation", "birth"]);
    await screen.getByText("Thông tin bổ sung", { exact: true }).click();
    await expect.element(screen.getByRole("list")).toBeVisible();
    const noteItems = screen.getByRole("listitem").all();
    expect(noteItems).toHaveLength(2);
    await expect
      .element(noteItems[0])
      .toHaveTextContent("Không có kinh nghiệm");
    await expect
      .element(noteItems[1])
      .toHaveTextContent("Hỏi về bảo hiểm tại LG Display");
  });

  it("lets an authorized recruiter edit real profile fields atomically", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const screen = await render(
      <TestMessages>
        <div className="inbox-bg-container">
          <ConversationContextPanel
            lead={{ ...lead, version: 4 }}
            open
            persistent
            canEdit
            onSave={onSave}
            onClose={() => undefined}
          />
        </div>
      </TestMessages>,
    );

    await screen
      .getByRole("button", { name: "Chỉnh sửa hồ sơ ứng viên" })
      .click();
    await expect
      .element(screen.getByLabelText("Họ tên"))
      .toHaveAttribute("autocomplete", "name");
    await expect
      .element(screen.getByLabelText("Số điện thoại"))
      .toHaveAttribute("type", "tel");
    await expect
      .element(screen.getByLabelText("Số điện thoại"))
      .toHaveAttribute("autocomplete", "tel");
    await screen.getByLabelText("Họ tên").fill("  Nguyễn Hùng  ");
    await screen.getByLabelText("Tuổi").fill("32");
    await screen
      .getByLabelText("Ghi chú (CCCD, chỗ ở, xe đưa đón và thông tin khác)")
      .fill("");
    await screen.getByRole("button", { name: "Lưu thay đổi" }).click();

    await expect.poll(() => onSave.mock.calls.length).toBe(1);
    expect(onSave).toHaveBeenCalledWith(
      {
        name: "Nguyễn Hùng",
        age: 32,
        notes: null,
      },
      4,
    );
  });

  it("cancels edits without saving", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const screen = await render(
      <TestMessages>
        <div className="inbox-bg-container">
          <ConversationContextPanel
            lead={lead}
            open
            persistent
            canEdit
            onSave={onSave}
            onClose={() => undefined}
          />
        </div>
      </TestMessages>,
    );

    await screen
      .getByRole("button", { name: "Chỉnh sửa hồ sơ ứng viên" })
      .click();
    await screen.getByLabelText("Họ tên").fill("Tên chưa lưu");
    await screen.getByRole("button", { name: "Hủy" }).click();

    await expect
      .element(screen.getByText("Ứng viên mẫu", { exact: true }).first())
      .toBeVisible();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("opens the candidate context as a named modal on a phone", async () => {
    mobileMock.isMobile = true;
    const onClose = vi.fn();
    const onCloseAutoFocus = vi.fn();
    const screen = await render(
      <TestMessages>
        <ConversationContextPanel
          lead={lead}
          open
          onClose={onClose}
          onCloseAutoFocus={onCloseAutoFocus}
        />
      </TestMessages>,
    );

    await expect
      .element(screen.getByRole("dialog", { name: "Thông tin ứng viên" }))
      .toBeVisible();

    await screen
      .getByRole("button", { name: "Đóng thông tin ứng viên" })
      .click();

    await expect.poll(() => onClose.mock.calls.length).toBe(1);
    expect(onCloseAutoFocus).toHaveBeenCalledTimes(1);
  });

  it("does not expose profile editing without recruiter edit permission", async () => {
    const screen = await render(
      <TestMessages>
        <div className="inbox-bg-container">
          <ConversationContextPanel
            lead={lead}
            open
            persistent
            canEdit={false}
            onSave={vi.fn().mockResolvedValue(undefined)}
            onClose={() => undefined}
          />
        </div>
      </TestMessages>,
    );

    await expect
      .element(
        screen
          .getByRole("button", { name: "Chỉnh sửa hồ sơ ứng viên" })
          .query(),
      )
      .not.toBeInTheDocument();
  });
});

describe("ConversationContextPanel project interests", () => {
  it("shows the dự án the candidate is interested in, oldest first", async () => {
    apiJsonMock.mockResolvedValue([
      {
        project_id: "p1",
        project_slug: "lg-display",
        project_name: "LG Display",
        source: "chat_focus",
        first_interested_at: "2026-10-01T00:00:00Z",
      },
      {
        project_id: "p2",
        project_slug: "ssg-bac-ninh",
        project_name: "SSG Bắc Ninh",
        source: "chat_focus",
        first_interested_at: "2026-10-02T00:00:00Z",
      },
    ]);

    const screen = await render(
      <TestMessages>
        <div className="inbox-bg-container">
          <ConversationContextPanel
            lead={lead}
            open
            persistent
            onClose={() => undefined}
          />
        </div>
      </TestMessages>,
    );

    expect(apiJsonMock).toHaveBeenCalledWith(
      "/api/v1/leads/1/project-interests",
      expect.objectContaining({ signal: expect.anything() }),
    );
    await expect.element(screen.getByText("Dự án quan tâm")).toBeVisible();
    await expect
      .element(screen.getByText("LG Display · SSG Bắc Ninh"))
      .toBeVisible();
  });

  it("omits the row when no interest is recorded", async () => {
    const screen = await render(
      <TestMessages>
        <div className="inbox-bg-container">
          <ConversationContextPanel
            lead={lead}
            open
            persistent
            onClose={() => undefined}
          />
        </div>
      </TestMessages>,
    );

    await expect
      .element(screen.getByText("Dự án quan tâm").query())
      .not.toBeInTheDocument();
  });

  it("never surfaces a failed interest read as an error", async () => {
    apiJsonMock.mockRejectedValue(new Error("offline"));

    const screen = await render(
      <TestMessages>
        <div className="inbox-bg-container">
          <ConversationContextPanel
            lead={lead}
            open
            persistent
            onClose={() => undefined}
          />
        </div>
      </TestMessages>,
    );

    await expect
      .element(screen.getByText("Dự án quan tâm").query())
      .not.toBeInTheDocument();
    await expect
      .element(screen.getByText("Ứng viên mẫu", { exact: true }).first())
      .toBeVisible();
  });
});
