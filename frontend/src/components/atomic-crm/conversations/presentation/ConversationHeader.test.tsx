import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import type { ReactNode } from "react";
import type { ConversationContextValue } from "../../capabilities/types";
import { ConversationHeader } from "./ConversationHeader";
import { ConversationReplyMode } from "./ConversationReplyMode";
import "@/index.css";
import "../inbox.css";

const identity: ConversationContextValue = {
  displayName: "Biệt danh của ứng viên có tên rất dài để kiểm tra bố cục",
  avatarAlt: "Ảnh đại diện thử nghiệm",
  contactSubtitle: { secondaryName: "Tên đã xác nhận", phone: "0900000000" },
  panelLabel: "Thông tin ứng viên",
};

// The real header is a grid row in the center pane. Placing an inline-size
// container directly in the flex inbox root gives it zero intrinsic width.
// Keep the actual hierarchy, with one bounded pane instead of a second list.
const InboxPane = ({
  header,
  toolbar,
  width = 620,
}: {
  header?: ReactNode;
  toolbar?: ReactNode;
  width?: number;
}) => (
  <main className="workspace-frame-content" style={{ width, height: 844 }}>
    <div className="inbox-bg-container conversation-workspace">
      <div
        className="app detail-open has-selected-conversation"
        style={{ gridTemplateColumns: "minmax(0, 1fr)" }}
      >
        <section className="panel center-panel">
          {header ?? <header className="chat-header" />}
          <div className="chat-scroll-shell" />
          <footer className="composer-wrap">{toolbar}</footer>
        </section>
      </div>
    </div>
  </main>
);

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 900);
});

describe("conversation identity header", () => {
  it.each([
    [320, 300],
    [360, 340],
    [390, 370],
    [900, 420],
    [1440, 620],
  ])(
    "keeps one candidate target and readable contact at viewport %i / pane %i",
    async (viewport, pane) => {
      await page.viewport(viewport, 844);
      const open = vi.fn();
      const screen = await render(
        <InboxPane
          width={pane}
          header={
            <ConversationHeader
              identity={identity}
              candidateOpen={false}
              onOpenCandidate={open}
              onBack={vi.fn()}
              actions={
                <button
                  type="button"
                  className="conversation-header-actions-button"
                >
                  ⋯
                </button>
              }
            />
          }
        />,
      );
      const header = screen.container.querySelector<HTMLElement>(
        ".conversation-header",
      )!;
      const target = screen.getByRole("button", {
        name: `Xem thông tin ứng viên của ${identity.displayName}`,
      });
      await expect.element(target).toBeVisible();
      await expect.element(target).toHaveAccessibleDescription("0900000000");
      expect(
        screen.container.querySelectorAll(
          ".conversation-header-identity-button",
        ),
      ).toHaveLength(1);
      await expect
        .element(screen.getByText("0900000000", { exact: true }))
        .toBeVisible();
      expect(header.scrollWidth).toBeLessThanOrEqual(header.clientWidth + 1);
      const bounds = header.getBoundingClientRect();
      const phone = screen.container
        .querySelector<HTMLElement>(".conversation-header-phone")!
        .getBoundingClientRect();
      expect(phone.right).toBeLessThanOrEqual(bounds.right + 1);
      expect(phone.left).toBeGreaterThanOrEqual(bounds.left);
      for (const button of screen.container.querySelectorAll<HTMLButtonElement>(
        ".conversation-header button",
      )) {
        if (getComputedStyle(button).display === "none") continue;
        expect(button.getBoundingClientRect().height).toBeGreaterThanOrEqual(
          44,
        );
      }
      await target.click();
      expect(open).toHaveBeenCalledTimes(1);
    },
  );

  it("shows missing phone honestly and offers no candidate action when unavailable", async () => {
    const screen = await render(
      <InboxPane
        header={
          <ConversationHeader
            identity={{ ...identity, contactSubtitle: undefined }}
            candidateOpen={false}
          />
        }
      />,
    );
    await expect
      .element(screen.getByText("Chưa có số điện thoại"))
      .toBeVisible();
    expect(screen.container.querySelector("button")).toBeNull();
  });

  it("keeps the missing-phone status readable in a narrow phone pane", async () => {
    await page.viewport(320, 844);
    const screen = await render(
      <InboxPane
        width={300}
        header={
          <ConversationHeader
            identity={{ ...identity, contactSubtitle: undefined }}
            candidateOpen={false}
            onOpenCandidate={vi.fn()}
            onBack={vi.fn()}
            actions={
              <button
                type="button"
                className="conversation-header-actions-button"
              >
                ⋯
              </button>
            }
          />
        }
      />,
    );
    const header = screen.container.querySelector<HTMLElement>(
      ".conversation-header",
    )!;
    await expect
      .element(screen.getByText("Chưa có số điện thoại"))
      .toBeVisible();
    expect(header.scrollWidth).toBeLessThanOrEqual(header.clientWidth + 1);
    const bounds = header.getBoundingClientRect();
    const phone = screen.container
      .querySelector<HTMLElement>(".conversation-header-phone")!
      .getBoundingClientRect();
    expect(phone.right).toBeLessThanOrEqual(bounds.right + 1);
  });
});

describe("composer reply-mode control", () => {
  it.each([
    ["bot", "Chatbot"],
    ["human", "Tư vấn viên"],
    ["semi_auto", "Bán tự động"],
  ] as const)("keeps the %s mode visible on phones", async (mode, label) => {
    await page.viewport(390, 844);
    const screen = await render(
      <InboxPane
        width={370}
        toolbar={
          <ConversationReplyMode
            mode={mode}
            needsClaim={false}
            onChange={vi.fn()}
          />
        }
      />,
    );
    const trigger = screen.getByRole("button", { name: "Đổi chế độ trả lời" });
    await expect.element(trigger).toHaveTextContent(`Chế độ: ${label}`);
    const button = screen.container.querySelector<HTMLButtonElement>(
      ".reply-mode-trigger",
    )!;
    expect(button.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
  });

  it.each([
    { needsClaim: true, isChangingMode: false },
    { needsClaim: false, isChangingMode: true },
  ])("keeps claim/pending guards intact: %j", async (guard) => {
    const change = vi.fn();
    const screen = await render(
      <ConversationReplyMode mode="human" {...guard} onChange={change} />,
    );
    await expect
      .element(screen.getByRole("button", { name: "Đổi chế độ trả lời" }))
      .toBeDisabled();
    expect(change).not.toHaveBeenCalled();
  });

  it("changes to the selected mode and marks the current menu option", async () => {
    const change = vi.fn();
    const screen = await render(
      <ConversationReplyMode mode="bot" needsClaim={false} onChange={change} />,
    );
    await screen.getByRole("button", { name: "Đổi chế độ trả lời" }).click();
    await expect
      .element(screen.getByRole("menuitem", { name: /^Chatbot\s/ }))
      .toHaveAccessibleName(/^Chatbot\s.*Đang chọn/);
    await screen.getByRole("menuitem", { name: /Tư vấn viên/ }).click();
    expect(change).toHaveBeenCalledExactlyOnceWith("human");
  });

  it("does not offer mode changes for closed conversations", async () => {
    const screen = await render(
      <ConversationReplyMode
        mode="closed"
        needsClaim={false}
        onChange={vi.fn()}
      />,
    );
    expect(screen.container.querySelector("button")).toBeNull();
    expect(screen.container.textContent).toBe("");
  });
});
