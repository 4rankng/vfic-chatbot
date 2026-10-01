import { cleanup, render } from "vitest-browser-react";
import { userEvent } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TestMessages } from "../atomic-crm/providers/commons/TestMessages";
import { Confirm } from "./confirm";

afterEach(async () => {
  await cleanup();
});

describe("destructive confirmation", () => {
  it("keeps an in-flight action visible and blocks Escape or repeat confirmation", async () => {
    const onClose = vi.fn();
    const onConfirm = vi.fn();
    const screen = await render(
      <TestMessages>
        <Confirm
          isOpen
          loading
          title="Xóa cuộc trò chuyện"
          content="Cuộc trò chuyện đang được xóa."
          onClose={onClose}
          onConfirm={onConfirm}
        />
      </TestMessages>,
    );

    await userEvent.keyboard("{Escape}");

    expect(onClose).not.toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
    await expect
      .element(screen.getByRole("button", { name: "Đóng" }))
      .not.toBeInTheDocument();
    await expect
      .element(screen.getByRole("button", { name: "Xác nhận" }))
      .toBeDisabled();
    await expect
      .element(screen.getByRole("dialog"))
      .toHaveAttribute("aria-busy", "true");
  });

  it("still allows closing before confirmation starts", async () => {
    const onClose = vi.fn();
    const screen = await render(
      <TestMessages>
        <Confirm
          isOpen
          title="Xóa cuộc trò chuyện"
          content="Hãy kiểm tra trước khi xóa."
          onClose={onClose}
          onConfirm={vi.fn()}
        />
      </TestMessages>,
    );

    await screen.getByRole("button", { name: "Đóng" }).click();

    expect(onClose).toHaveBeenCalledOnce();
  });
});
