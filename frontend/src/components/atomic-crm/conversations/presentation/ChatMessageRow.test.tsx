// a-c-chat-01 bubble anatomy, measured on the rendered row.
//
// Two cascade layers both declared `.bubble` and disagreed about the bubble's
// near-corner radius and fill, so the anatomy is pinned on the computed style of
// the real component inside the real `.inbox-bg-container` scope rather than on
// a stylesheet's source text — the TEST-17 shape this repo uses for feature CSS.
//
// The fills are compared against probes painted from the same `--tt-*` tokens,
// so the assertion is "the bubble wears the muted / brand role", not a hex value
// a palette refresh would invalidate. A transparent probe fails the test loudly
// instead of letting both sides compare equal.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";

import "@/index.css";
import "../inbox.css";

vi.mock("ra-core", () => ({
  // The row only needs a translator; the Vietnamese copy is not under test here.
  useTranslate: () => (key: string) => key,
}));

import { ChatMessageRow } from "./ChatMessageRow";
import type { ConversationMessageKind } from "../domain/conversation-thread-rows";
import type { Message } from "../../types";

const message = (type: Message["type"]): Message => ({
  id: "m-1",
  zalo_message_id: "z-1",
  conversation_id: "conv-1",
  type,
  content: "Xin chào",
  data: null,
  created_at: "2026-07-01T00:00:00.000Z",
});

/** The row inside the inbox scope the console renders it in. */
const frame = (kind: ConversationMessageKind) => (
  <div className="inbox-bg-container">
    <div className="chat-scroller">
      <ChatMessageRow
        message={message(kind === "user" ? "inbound" : "outbound")}
        kind={kind}
        isGrouped={false}
      />
    </div>
    <span
      data-probe="muted"
      style={{ backgroundColor: "var(--tt-surface-muted)" }}
    />
    <span data-probe="accent" style={{ backgroundColor: "var(--tt-accent)" }} />
  </div>
);

describe("ChatMessageRow — a-c-chat-01 bubble anatomy", () => {
  beforeEach(async () => {
    // The anatomy is breakpoint-independent; pin the desktop viewport known to
    // the container queries in the inbox sheets.
    await page.viewport(1280, 900);
  });

  afterEach(async () => {
    await cleanup();
  });

  it("squares the near bottom corner of an inbound bubble on the muted surface", async () => {
    const screen = await render(frame("user"));
    const muted = getComputedStyle(
      screen.container.querySelector<HTMLElement>(`[data-probe="muted"]`)!,
    ).backgroundColor;
    expect(muted).not.toBe("rgba(0, 0, 0, 0)");

    const style = getComputedStyle(
      screen.container.querySelector<HTMLElement>(".bubble")!,
    );
    expect(style.borderTopLeftRadius).toBe("16px");
    expect(style.borderTopRightRadius).toBe("16px");
    expect(style.borderBottomRightRadius).toBe("16px");
    expect(style.borderBottomLeftRadius).toBe("0px");
    expect(style.paddingTop).toBe("12px");
    expect(style.paddingLeft).toBe("12px");
    expect(style.borderTopWidth).toBe("0px");
    expect(style.backgroundColor).toBe(muted);
  });

  it("squares the near bottom corner of an outbound bubble on the brand fill", async () => {
    const screen = await render(frame("agent"));
    const accent = getComputedStyle(
      screen.container.querySelector<HTMLElement>(`[data-probe="accent"]`)!,
    ).backgroundColor;
    expect(accent).not.toBe("rgba(0, 0, 0, 0)");

    const style = getComputedStyle(
      screen.container.querySelector<HTMLElement>(".bubble")!,
    );
    expect(style.borderTopLeftRadius).toBe("16px");
    expect(style.borderBottomLeftRadius).toBe("16px");
    expect(style.borderBottomRightRadius).toBe("0px");
    expect(style.paddingTop).toBe("12px");
    expect(style.paddingLeft).toBe("12px");
    expect(style.borderTopWidth).toBe("0px");
    expect(style.backgroundColor).toBe(accent);
    expect(style.color).toBe("rgb(255, 255, 255)");
  });
});
