import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { mockApiJson } = vi.hoisted(() => ({
  mockApiJson: vi.fn(),
}));

vi.mock("../providers/rest/api", () => ({
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
});

describe("ChannelAdapterSelector", () => {
  it("renders an exclusive Vietnamese radio selector and switches scope", async () => {
    const onProviderChange = vi.fn();
    const screen = await render(
      <div className="inbox-bg-container">
        <ChannelAdapterSelectorView
          provider="zalo_bot"
          counts={{ zalo_bot: 0, zalo_oa: 135 }}
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
    await expect
      .element(screen.getByText("Kênh đang chọn:", { exact: false }))
      .toHaveTextContent("Kênh đang chọn: Zalo Chatbot");
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
    // The browser-test viewport is narrow, so the mobile 48 px target applies;
    // the base CSS keeps the desktop target at 44 px.
    expect(getComputedStyle(oaElement as Element).width).toBe("48px");
    expect(
      oaElement?.querySelector('[data-slot="radio-group-indicator"]'),
    ).toBeNull();

    await oaRadio.hover();
    await expect
      .element(screen.getByRole("tooltip"))
      .toHaveTextContent("Zalo OA — 135 hội thoại cần phản hồi");

    await oaRadio.click();
    expect(onProviderChange).toHaveBeenCalledWith("zalo_oa");
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

    await expect.poll(() => mockApiJson.mock.calls.length).toBe(2);
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
    await expect
      .element(screen.getByText("Kênh đang chọn:", { exact: false }))
      .toHaveTextContent(
        "Kênh đang chọn: Zalo Chatbot · 2 hội thoại cần phản hồi",
      );

    await screen
      .getByRole("radio", {
        name: "Zalo OA — 4 hội thoại cần phản hồi",
      })
      .click();
    const next = onSearchParamsChange.mock.calls[0]?.[0] as URLSearchParams;
    expect(next.get("channel_provider")).toBe("zalo_oa");
    expect(next.get("reason")).toBe("UNREAD");
    expect(next.has("id")).toBe(false);
  });
});
