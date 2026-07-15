import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it } from "vitest";

import { IngestionTemplateBuilder } from "./IngestionTemplateBuilder";

afterEach(async () => {
  await cleanup();
});

describe("IngestionTemplateBuilder", () => {
  it("opens with empty admin-owned fields and no industry/customer starter data", async () => {
    const screen = await render(<IngestionTemplateBuilder />);
    await screen.getByRole("button", { name: "Mẫu ingest" }).click();

    await expect.element(screen.getByLabelText("Tên mẫu")).toHaveValue("");
    await expect.element(screen.getByLabelText("Lĩnh vực")).toHaveValue("");
    await expect.element(screen.getByLabelText("Loại bản ghi")).toHaveValue("");
    await expect
      .element(screen.getByLabelText("Các trường (cách nhau dấu phẩy)"))
      .toHaveValue("");
    await expect.element(screen.getByLabelText("Dữ liệu thử")).toHaveValue("");
    await expect.element(screen.getByText("Tuyển dụng")).not.toBeInTheDocument();
    await expect.element(screen.getByText("Logistics")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("VFIC");
  });
});
