import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PASTED_TEXT_FILENAME } from "../project-knowledge-service";
import { PasteTextArea } from "./PasteTextArea";

afterEach(async () => {
  await cleanup();
});

describe("brief paste area", () => {
  it("wraps the pasted text as the markdown source file the chain already accepts", async () => {
    const onSubmit = vi.fn();
    const screen = await render(
      <PasteTextArea onSubmit={onSubmit} onClose={vi.fn()} />,
    );
    const confirm = screen.getByRole("button", { name: "Nạp văn bản" });
    await expect.element(confirm).toBeDisabled();
    await screen
      .getByRole("textbox", { name: "Văn bản kiến thức dán vào" })
      .fill("Kiến thức tuyển dụng của dự án");
    await confirm.click();
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const file = onSubmit.mock.calls[0][0] as File;
    expect(file.name).toBe(PASTED_TEXT_FILENAME);
    expect(file.type).toBe("text/markdown");
    expect(await file.text()).toBe("Kiến thức tuyển dụng của dự án");
  });

  it("stays available while busy and lets the operator back out", async () => {
    const onClose = vi.fn();
    const screen = await render(
      <PasteTextArea busy onSubmit={vi.fn()} onClose={onClose} />,
    );
    await expect
      .element(screen.getByRole("button", { name: "Nạp văn bản" }))
      .toBeDisabled();
    await expect
      .element(
        screen.getByRole("textbox", { name: "Văn bản kiến thức dán vào" }),
      )
      .toBeDisabled();
    await screen.getByRole("button", { name: "Hủy" }).click();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
