import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

import type { ConversationChannelProvider } from "../types";

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
import { useNotifications } from "@/components/atomic-crm/layout/topbar/useNotifications";
import "./inbox.css";

/** The workspace shell's real bell accessor, mounted beside the panel. */
const TopbarBellProbe = () => {
  const { count } = useNotifications();
  return <span data-testid="bell">{count}</span>;
};

afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
  // Restore the desktop viewport in case a test shrank the window.
  await page.viewport(1280, 720);
});

describe("ChannelAdapterSelector", () => {
  it("renders an exclusive Vietnamese radio selector and switches scope", async () => {
    // Directory-header density cap: the tile is 40px, down from 48px and then
    // 44px, so the header stays compact at every width.
    // Pin a mobile viewport so the inbox sheet's `@media (max-width: 767px)`
    // rules are the ones under test.
    await page.viewport(414, 896);
    const onProviderChange = vi.fn();
    const screen = await render(
      <div className="inbox-bg-container">
        <ChannelAdapterSelectorView
          provider="zalo_bot"
          counts={{
            zalo_bot: 0,
            zalo_oa: 135,
            facebook_messenger: 0,
            tingting_oa: 0,
          }}
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
    // Zalo Chatbot, Zalo OA, Messenger, and the employee-support TingTing OA.
    expect(screen.getByRole("radio").all()).toHaveLength(4);
    await expect
      .element(screen.getByRole("radio", { name: "Zalo Chatbot" }))
      .toBeVisible();
    // Messenger and the TingTing support OA are selectable scopes alongside the
    // Zalo adapters.
    await expect
      .element(screen.getByRole("radio", { name: "Messenger" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("radio", { name: /Zalo OA TingTing/ }))
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
    // Owner-set density cap: every directory-header control is 40px or less.
    expect(getComputedStyle(oaElement as Element).width).toBe("40px");
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

    // The selected scope must stay visibly marked after the click, not just
    // while focused: the option doubles as a TooltipTrigger, so styling keyed
    // on data-state is silently overwritten by the tooltip's own state.
    // Which state hook marks the selection depends on the active inbox skin:
    // workspace-rail colors the border, untitledui colors the background (its
    // border shift is documented as a visual no-op). Assert "some state hook
    // differs" so the pin survives legitimate skin changes and CSS cascade
    // order in the shared test browser. Polled for style settlement.
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
      const visuallyMarked =
        checkedStyle.borderTopColor !== uncheckedStyle.borderTopColor ||
        checkedStyle.backgroundColor !== uncheckedStyle.backgroundColor;
      expect(visuallyMarked).toBe(true);
    });

    await oaRadio.click();
    expect(onProviderChange).toHaveBeenCalledWith("zalo_oa");

    await screen.getByRole("radio", { name: "Zalo Chatbot" }).click();
    expect(onProviderChange).toHaveBeenLastCalledWith(undefined);
  });

  it("reads every badge from the one shared counts query and clears only the conversation id", async () => {
    mockApiJson.mockImplementation(async (url: string) => {
      if (!url.includes("channel_provider")) return { count: 9 };
      if (url.includes("zalo_bot")) return { count: 2 };
      // The support OA is its own bucket: its key matches neither "zalo_bot"
      // nor the plain "zalo_oa" provider filter.
      if (url.includes("tingting_oa")) return { count: 1 };
      if (url.includes("zalo_oa")) return { count: 4 };
      return { count: 6 };
    });
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

    const oaRadio = screen.getByRole("radio", {
      name: "Zalo OA — 4 hội thoại cần phản hồi",
    });
    await expect.element(oaRadio).toBeVisible();
    // Messenger and the TingTing OA are scoped too, so the shared query must
    // cover every badge without a query of its own.
    await expect
      .element(
        screen.getByRole("radio", {
          name: "Messenger — 6 hội thoại cần phản hồi",
        }),
      )
      .toBeVisible();
    await expect
      .element(screen.getByRole("radio", { name: /Zalo OA TingTing/ }))
      .toBeVisible();

    // One unscoped count + one per badge (four now).
    expect(mockApiJson.mock.calls.length).toBe(5);
    expect(mockApiJson).toHaveBeenCalledWith(
      "/api/v1/conversations/needs-attention",
    );
    expect(mockApiJson).toHaveBeenCalledWith(
      "/api/v1/conversations/needs-attention?channel_provider=zalo_bot",
    );
    expect(mockApiJson).toHaveBeenCalledWith(
      "/api/v1/conversations/needs-attention?channel_provider=zalo_oa",
    );
    expect(mockApiJson).toHaveBeenCalledWith(
      "/api/v1/conversations/needs-attention?channel_provider=facebook_messenger",
    );
    expect(mockApiJson).toHaveBeenCalledWith(
      "/api/v1/conversations/needs-attention?channel_provider=tingting_oa",
    );
    // One cache entry holds every counter, and the total stays the server's
    // unscoped answer rather than the sum of the provider buckets.
    expect(
      queryClient.getQueryData(["conversations", "needs-attention", "counts"]),
    ).toEqual({
      total: 9,
      byProvider: {
        zalo_bot: 2,
        zalo_oa: 4,
        facebook_messenger: 6,
        tingting_oa: 1,
      },
    });

    await oaRadio.click();
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

  it("renders badges from the topbar's warm counts entry without polling again", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(["conversations", "needs-attention", "counts"], {
      total: 7,
      byProvider: { zalo_bot: 1, zalo_oa: 0, facebook_messenger: 6 },
    });
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <ChannelAdapterSelector
          provider={undefined}
          searchParams={new URLSearchParams()}
          onSearchParamsChange={vi.fn()}
        />
      </QueryClientProvider>,
    );

    await expect
      .element(
        screen.getByRole("radio", {
          name: "Zalo Chatbot — 1 hội thoại cần phản hồi",
        }),
      )
      .toBeVisible();
    await expect
      .element(
        screen.getByRole("radio", {
          name: "Messenger — 6 hội thoại cần phản hồi",
        }),
      )
      .toBeVisible();
    expect(mockApiJson).not.toHaveBeenCalled();
  });

  it("shares one counts poll between the topbar bell and the adapter badges", async () => {
    mockApiJson.mockImplementation(async (url: string) =>
      url.includes("channel_provider") ? { count: 1 } : { count: 3 },
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <TopbarBellProbe />
        <ChannelAdapterSelector
          provider={undefined}
          searchParams={new URLSearchParams()}
          onSearchParamsChange={vi.fn()}
        />
      </QueryClientProvider>,
    );

    await expect.element(screen.getByTestId("bell")).toHaveTextContent("3");
    await expect
      .element(
        screen.getByRole("radio", {
          name: "Messenger — 1 hội thoại cần phản hồi",
        }),
      )
      .toBeVisible();

    // The panel and the bell ride the same query: one unscoped count plus one
    // per badge, once per interval, one cache entry — not one poller each.
    expect(mockApiJson.mock.calls.length).toBe(5);
    expect(queryClient.getQueryCache().getAll()).toHaveLength(1);
  });

  it("toggles the active filter off and drops the selection highlight", async () => {
    // Tap-to-filter, tap-again-to-clear: the second tap on the active channel
    // must clear the selection state (aria-checked/data-state) so no skin
    // keeps painting it as the active filter.
    const Harness = () => {
      const [provider, setProvider] = useState<
        ConversationChannelProvider | undefined
      >("zalo_bot");
      return (
        <div className="inbox-bg-container">
          <ChannelAdapterSelectorView
            provider={provider}
            counts={{
              zalo_bot: 0,
              zalo_oa: 0,
              facebook_messenger: 0,
              tingting_oa: 0,
            }}
            onProviderChange={setProvider}
          />
        </div>
      );
    };
    const screen = await render(<Harness />);

    const zaloBot = screen.getByRole("radio", { name: "Zalo Chatbot" });
    await expect.element(zaloBot).toBeChecked();
    await zaloBot.click();

    const option = screen.container.querySelector(
      '.channel-adapter-option[value="zalo_bot"]',
    ) as HTMLElement;
    // aria-checked is the state hook both inbox skins key the highlight on;
    // data-state on this element belongs to the Tooltip trigger (see the
    // selector-scope test above).
    expect(option.getAttribute("aria-checked")).toBe("false");
  });
});
