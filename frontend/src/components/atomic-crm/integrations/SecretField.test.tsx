import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { copyCredentialFieldValue } from "./credentialClipboard";
import { PlainField, SecretField } from "./SecretField";

afterEach(async () => {
  await cleanup();
});

const setClipboard = (writeText: unknown) => {
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: writeText === undefined ? undefined : { writeText },
  });
};

describe("SecretField", () => {
  it("uses the preview placeholder and toggles the revealed value", async () => {
    const notify = vi.fn();
    const onValueChange = vi.fn();
    const screen = await render(
      <SecretField
        id="zalo_bot_token"
        label="Bot Token"
        configured
        preview="dev-…oken"
        value="secret-value"
        placeholder="Nhập giá trị"
        onChange={onValueChange}
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
      <SecretField
        id="zalo_oa_access_token"
        label="OA Access Token"
        configured={false}
        value=""
        placeholder="Nhập giá trị"
        onChange={vi.fn()}
        notify={vi.fn()}
      />,
    );

    const input = screen.getByRole("textbox", { name: "OA Access Token" });
    await expect.element(input).toHaveAttribute("placeholder", "Nhập giá trị");
    await expect
      .element(screen.getByRole("button", { name: "Sao chép OA Access Token" }))
      .toBeDisabled();
  });

  it("fetches the stored secret on demand and locks the field while revealed", async () => {
    const reveal = vi.fn().mockResolvedValue("stored-plaintext");
    const screen = await render(
      <SecretField
        id="facebook_app_secret"
        label="App Secret"
        configured
        preview="…cdef"
        value=""
        placeholder="Nhập giá trị mới"
        onChange={vi.fn()}
        reveal={reveal}
      />,
    );

    const input = screen.getByRole("textbox", { name: "App Secret" });
    await expect
      .element(input)
      .toHaveAttribute("placeholder", "Hiện tại: …cdef");
    // A field the page did not ask to be copyable offers no copy action.
    expect(
      screen.getByRole("button", { name: "Sao chép App Secret" }).query(),
    ).toBeNull();

    await screen.getByRole("button", { name: "Hiện App Secret" }).click();

    await expect.poll(() => reveal.mock.calls.length).toBe(1);
    await expect.element(input).toHaveAttribute("type", "text");
    await expect.element(input).toHaveValue("stored-plaintext");
    expect((input.element() as HTMLInputElement).readOnly).toBe(true);

    // Hiding again drops the plaintext instead of re-fetching it.
    await screen.getByRole("button", { name: "Ẩn App Secret" }).click();
    await expect.element(input).toHaveValue("");
    expect((input.element() as HTMLInputElement).readOnly).toBe(false);
    expect(reveal.mock.calls.length).toBe(1);
  });

  it("offers no reveal action for an unconfigured secret with no stored value", async () => {
    const screen = await render(
      <SecretField
        id="facebook_app_secret"
        label="App Secret"
        configured={false}
        value=""
        placeholder="Nhập giá trị mới"
        onChange={vi.fn()}
        reveal={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Hiện App Secret" }).query(),
    ).toBe(null);
  });
});

describe("PlainField", () => {
  it("copies the plain value when the page supplies a toast channel", async () => {
    const notify = vi.fn();
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard(writeText);
    const screen = await render(
      <PlainField
        id="zalo_oa_app_id"
        label="Zalo App ID"
        configured
        value="1234567890"
        onChange={vi.fn()}
        notify={notify}
      />,
    );

    await screen.getByRole("button", { name: "Sao chép Zalo App ID" }).click();

    await expect.poll(() => writeText.mock.calls).toEqual([["1234567890"]]);
    expect(notify).toHaveBeenCalledWith("Đã sao chép Zalo App ID.", {
      type: "success",
    });
  });

  it("hides an optional field's missing status until it is configured", async () => {
    const screen = await render(
      <PlainField
        id="facebook_login_config_id"
        label="Configuration ID"
        configured={false}
        showMissingStatus={false}
        value=""
        onChange={vi.fn()}
      />,
    );

    expect(
      screen.container.querySelector(
        'label[for="facebook_login_config_id"] ~ .settings-field-status',
      ),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "Sao chép Configuration ID" }).query(),
    ).toBeNull();
  });
});

describe("copyCredentialFieldValue", () => {
  it("reports successful clipboard writes", async () => {
    const notify = vi.fn();
    const clipboardWrite = vi.fn().mockResolvedValue(undefined);
    setClipboard(clipboardWrite);

    await copyCredentialFieldValue("Bot Token", "secret-value", notify);

    expect(clipboardWrite).toHaveBeenCalledWith("secret-value");
    expect(notify).toHaveBeenCalledWith("Đã sao chép Bot Token.", {
      type: "success",
    });
  });

  it("reports rejected and unavailable clipboard writes", async () => {
    const rejectedNotify = vi.fn();
    const unavailableNotify = vi.fn();
    setClipboard(vi.fn().mockRejectedValue(new Error("Clipboard unavailable")));

    await copyCredentialFieldValue("Bot Token", "secret-value", rejectedNotify);

    expect(rejectedNotify).toHaveBeenCalledWith(
      "Không thể sao chép Bot Token.",
      { type: "error" },
    );

    setClipboard(undefined);

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
