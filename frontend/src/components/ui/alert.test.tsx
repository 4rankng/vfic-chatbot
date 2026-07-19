import { cleanup, render } from "vitest-browser-react"
import { afterEach, describe, expect, it } from "vitest"

import { Alert, AlertDescription, AlertTitle } from "./alert"

afterEach(async () => {
  await cleanup()
})

describe("Alert", () => {
  it("delegates soft info contrast to the daisyUI semantic theme", async () => {
    const screen = await render(
      <Alert variant="info">
        <AlertTitle>Thông tin bảo mật</AlertTitle>
        <AlertDescription>Khóa được lưu trong kho mã hóa.</AlertDescription>
      </Alert>
    )

    const alert = screen.getByRole("alert")
    await expect.element(alert).toHaveClass("tt-alert-info")
    await expect.element(alert).toHaveClass("tt-alert-soft")
    await expect.element(alert).not.toHaveClass("text-info")
  })
})
