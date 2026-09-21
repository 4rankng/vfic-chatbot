import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

const { mockApiJson } = vi.hoisted(() => ({
  mockApiJson: vi.fn(),
}));

vi.mock("@/lib/apiClient", () => ({
  apiJson: mockApiJson,
}));

import {
  ChannelAdapterSelector,
  ChannelAdapterSelectorView,
} from "./ChannelAdapterSelector";
import "./inbox.css";

afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
  // Restore the desktop viewport in case a test shrank the window.
  await page.viewport(1280, 720);
});

describe("ChannelAdapterSelector", () => {
  it("renders an exclusive Vietnamese radio selector and switches scope", async () => {
    // Compact conversation toolbar keeps the visual control at the 44px
    // accessible touch-target minimum rather than the previous 48px tile.
    // Pin a mobile viewport so the @media (max-width: 767px) rules in
    // tailkit-redesign.css are the ones under test.
    await page.viewport(414, 896);
    const onProviderChange = vi.fn();
    const screen = await render(
      <div className="inbox-bg-container">
        <ChannelAdapterSelectorView
          provider="zalo_bot"
          counts={{ zalo_bot: 0, zalo_oa: 135, facebook_messenger: 0 }}
          onProviderChange={onProviderChange}
        />
      </div>,
    );

    const group = screen.getByRole("radiogroup", {
      name: "Chọn kênh hội thoại",
    });
    await expect.element(group).toBeVisible();
    await expect
      .element(screen.getByRole("radio", { name: "Zalo Chatbot" }))
      .toBeChecked();
    expect(screen.getByRole("radio").all()).toHaveLength(3);
    await expect
      .element(screen.getByRole("radio", { name: "Zalo Chatbot" }))
      .toBeVisible();
    // Messenger is a selectable scope alongside the Zalo adapters.
    await expect
      .element(screen.getByRole("radio", { name: "Messenger" }))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain("Kênh đang chọn:");
    await expect.element(screen.getByText("99+")).toBeVisible();
    expect(
      screen.container.querySelectorAll(".channel-adapter-badge"),
    ).toHaveLength(1);

    const oaRadio = screen.getByRole("radio", {
      name: "Zalo OA — 135 hội thoại cần phản hồi",
    });
    await expect.element(oaRadio).toBeVisible();
    const oaElement = screen.container.querySelector('[value="zalo_oa"]');
    expect(oaElement).not.toBeNull();
    expect(getComputedStyle(oaElement as Element).width).toBe("44px");
    expect(getComputedStyle(oaElement as Element).backgroundColor).not.toBe(
      "rgb(255, 255, 255)",
    );
    expect(
      getComputedStyle(oaElement?.querySelector("img") as Element).width,
    ).toBe("44px");
    expect(
      oaElement?.querySelector('[data-slot="radio-group-indicator"]'),
    ).toBeNull();

    await oaRadio.hover();
    await expect
      .element(screen.getByRole("tooltip"))
      .toHaveTextContent("Zalo OA — 135 hội thoại cần phản hồi");

    // The selected scope must stay visually marked after the click, not just
    // while focused: the option doubles as a TooltipTrigger, so styling keyed
    // on data-state is silently overwritten by the tooltip's own state.
    // Polled: under full-suite browser contention the computed border color
    // settles after the synchronous sample would have run.
    await vi.waitFor(() => {
      const checked = screen.container.querySelector(
        '.channel-adapter-option[aria-checked="true"]',
      );
      const unchecked = screen.container.querySelector(
        '.channel-adapter-option[aria-checked="false"]',
      );
      expect(checked).not.toBeNull();
      expect(unchecked).not.toBeNull();
      const checkedStyle = getComputedStyle(checked as Element);
      const uncheckedStyle = getComputedStyle(unchecked as Element);
      expect(checkedStyle.borderTopColor).not.toBe(
        uncheckedStyle.borderTopColor,
      );
    });

    await oaRadio.click();
    expect(onProviderChange).toHaveBeenCalledWith("zalo_oa");

    await screen.getByRole("radio", { name: "Zalo Chatbot" }).click();
    expect(onProviderChange).toHaveBeenLastCalledWith(undefined);
  });

  it("mounts distinct scoped count queries and clears only the conversation id", async () => {
    mockApiJson.mockImplementation(async (url: string) => ({
      count: url.includes("zalo_bot") ? 2 : 4,
    }));
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const onSearchParamsChange = vi.fn();
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ChannelAdapterSelector
          provider="zalo_bot"
          searchParams={
            new URLSearchParams(
              "channel_provider=zalo_bot&reason=UNREAD&id=conversation-1",
            )
          }
          onSearchParamsChange={onSearchParamsChange}
        />
      </QueryClientProvider>,
    );

    await expect.poll(() => mockApiJson.mock.calls.length).toBe(3);
    expect(mockApiJson).toHaveBeenCalledWith(
      "/api/v1/conversations/needs-attention?channel_provider=zalo_bot",
    );
    expect(mockApiJson).toHaveBeenCalledWith(
      "/api/v1/conversations/needs-attention?channel_provider=zalo_oa",
    );
    expect(
      queryClient.getQueryData(["conversations-needs-attention", "zalo_bot"]),
    ).toEqual({ count: 2 });
    expect(
      queryClient.getQueryData(["conversations-needs-attention", "zalo_oa"]),
    ).toEqual({ count: 4 });
    await screen
      .getByRole("radio", {
        name: "Zalo OA — 4 hội thoại cần phản hồi",
      })
      .click();
    const next = onSearchParamsChange.mock.calls[0]?.[0] as URLSearchParams;
    expect(next.get("channel_provider")).toBe("zalo_oa");
    expect(next.get("reason")).toBe("UNREAD");
    expect(next.has("id")).toBe(false);

    await screen
      .getByRole("radio", { name: "Zalo Chatbot — 2 hội thoại cần phản hồi" })
      .click();
    const aggregate = onSearchParamsChange.mock
      .calls[1]?.[0] as URLSearchParams;
    expect(aggregate.has("channel_provider")).toBe(false);
    expect(aggregate.get("reason")).toBe("UNREAD");
    expect(aggregate.has("id")).toBe(false);
  });
});
