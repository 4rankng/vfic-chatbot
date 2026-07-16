import { describe, expect, it, vi } from "vitest";

const { useQueryMock } = vi.hoisted(() => ({ useQueryMock: vi.fn() }));

vi.mock("@tanstack/react-query", () => ({ useQuery: useQueryMock }));
vi.mock("../../providers/rest/api", () => ({ apiJson: vi.fn() }));

import { useNotifications } from "./useNotifications";

describe("useNotifications", () => {
  it("refreshes the reply count while the workspace remains mounted", () => {
    useQueryMock.mockReturnValue({ data: { count: 1 } });

    expect(useNotifications()).toEqual({ count: 1 });
    expect(useQueryMock).toHaveBeenCalledWith(
      expect.objectContaining({
        queryKey: ["conversations-needs-attention"],
        staleTime: 30_000,
        refetchInterval: 30_000,
      }),
    );
  });
});
