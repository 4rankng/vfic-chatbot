import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it } from "vitest";

import { Alert, AlertDescription, AlertTitle } from "./alert";

afterEach(async () => {
  await cleanup();
});

describe("Alert", () => {
  it("uses a readable ink color for a lightly tinted info surface", async () => {
    const screen = await render(
      <Alert variant="info">
        <AlertTitle>Thông tin bảo mật</AlertTitle>
        <AlertDescription>Khóa được lưu trong kho mã hóa.</AlertDescription>
      </Alert>,
    );

    const alert = screen.getByRole("alert");
    await expect.element(alert).toHaveClass("text-info");
    await expect
      .element(alert)
      .toHaveClass("*:data-[slot=alert-description]:text-info");
  });
});
