import { describe, expect, it, vi } from "vitest";

const { useQueryMock } = vi.hoisted(() => ({ useQueryMock: vi.fn() }));

vi.mock("@tanstack/react-query", () => ({ useQuery: useQueryMock }));
vi.mock("@/lib/apiClient", () => ({ apiJson: vi.fn() }));

import { useNotifications } from "./useNotifications";

describe("useNotifications", () => {
  it("refreshes the reply count while the workspace remains mounted", () => {
    useQueryMock.mockReturnValue({
      data: {
        total: 1,
        byProvider: { zalo_bot: 1, zalo_oa: 0, facebook_messenger: 0 },
      },
    });

    expect(useNotifications()).toEqual({ count: 1 });
    expect(useQueryMock).toHaveBeenCalledWith(
      expect.objectContaining({
        queryKey: ["conversations", "needs-attention", "counts"],
        staleTime: 60_000,
        refetchInterval: 60_000,
      }),
    );
  });

  it("reports no pending replies before the first counts response lands", () => {
    useQueryMock.mockReturnValue({ data: undefined });

    expect(useNotifications()).toEqual({ count: 0 });
  });
});
