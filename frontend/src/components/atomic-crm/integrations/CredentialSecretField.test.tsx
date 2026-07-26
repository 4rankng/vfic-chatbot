import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  copyCredentialFieldValue,
  CredentialSecretField,
} from "./CredentialSecretField";

afterEach(async () => {
  await cleanup();
});

describe("CredentialSecretField", () => {
  it("uses the preview placeholder and toggles the revealed value", async () => {
    const notify = vi.fn();
    const onValueChange = vi.fn();
    const screen = await render(
      <CredentialSecretField
        id="zalo_bot_token"
        label="Bot Token"
        status={{ configured: true, preview: "dev-…oken" }}
        value="secret-value"
        placeholder="Nhập giá trị"
        onValueChange={onValueChange}
        notify={notify}
      />,
    );

    const input = screen.getByRole("textbox", { name: "Bot Token" });
    await expect
      .element(input)
      .toHaveAttribute("placeholder", "Hiện tại: dev-…oken");
    await expect.element(input).toHaveAttribute("type", "password");

    await screen.getByRole("button", { name: "Hiện Bot Token" }).click();

    await expect.element(input).toHaveAttribute("type", "text");
    await input.fill("updated-secret");
    expect(onValueChange).toHaveBeenCalledWith("updated-secret");
  });

  it("uses the fallback placeholder and disables copying until a value exists", async () => {
    const screen = await render(
      <CredentialSecretField
        id="zalo_oa_access_token"
        label="OA Access Token"
        status={{ configured: false }}
        value=""
        placeholder="Nhập giá trị"
        onValueChange={vi.fn()}
        notify={vi.fn()}
      />,
    );

    const input = screen.getByRole("textbox", { name: "OA Access Token" });
    await expect.element(input).toHaveAttribute("placeholder", "Nhập giá trị");
    await expect
      .element(screen.getByRole("button", { name: "Sao chép OA Access Token" }))
      .toBeDisabled();
  });
});

describe("copyCredentialFieldValue", () => {
  it("reports successful clipboard writes", async () => {
    const notify = vi.fn();
    const clipboardWrite = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: { writeText: clipboardWrite },
    });

    await copyCredentialFieldValue("Bot Token", "secret-value", notify);

    expect(clipboardWrite).toHaveBeenCalledWith("secret-value");
    expect(notify).toHaveBeenCalledWith("Đã sao chép Bot Token.", {
      type: "success",
    });
  });

  it("reports rejected and unavailable clipboard writes", async () => {
    const rejectedNotify = vi.fn();
    const unavailableNotify = vi.fn();
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: vi.fn().mockRejectedValue(new Error("Clipboard unavailable")),
      },
    });

    await copyCredentialFieldValue(
      "Bot Token",
      "secret-value",
      rejectedNotify,
    );

    expect(rejectedNotify).toHaveBeenCalledWith(
      "Không thể sao chép Bot Token.",
      { type: "error" },
    );

    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });

    await copyCredentialFieldValue(
      "OA Access Token",
      "secret-value",
      unavailableNotify,
    );

    expect(unavailableNotify).toHaveBeenCalledWith(
      "Không thể sao chép OA Access Token.",
      { type: "error" },
    );
  });
});
