import { render } from "vitest-browser-react";
import type { Lead } from "../types";
import { ConversationContextPanel } from "./ConversationContextPanel";
import { TestMessages } from "@/components/atomic-crm/providers/commons/TestMessages";

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
