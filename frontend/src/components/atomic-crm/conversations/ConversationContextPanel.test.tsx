import { render } from "vitest-browser-react";
import type { Lead } from "../types";
import { ConversationContextPanel } from "./ConversationContextPanel";

const lead: Lead = {
  id: 1,
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
      <div className="inbox-bg-container">
        <ConversationContextPanel
          lead={lead}
          open
          persistent
          onClose={() => undefined}
        />
      </div>,
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
});
