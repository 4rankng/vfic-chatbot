import { afterEach, describe, expect, it, vi } from "vitest";

import { clearTokens } from "./api";
import { getDataProvider } from "./dataProvider";

/**
 * The REST dataProvider had zero tests. These cover the query-translation
 * contract every react-admin <List> depends on: page/per_page/sort/order
 * mapping, the id-sort skip, conversation mode normalization, and the
 * knowledge_sources -> knowledge/documents path alias.
 */
const provider = getDataProvider();

// vi.fn() stub so .mock.calls is available; the URL is captured in a closure
// for assertions (avoids reading vi.mocked(globalThis.fetch).mock, which is
// undefined when fetch is replaced with a plain function).
const stubList = (
  data: unknown[],
  total = data.length,
): { fetch: typeof globalThis.fetch; lastUrl: () => string } => {
  let url = "";
  const fn = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
    url = typeof input === "string" ? input : (input as URL).toString();
    return {
      ok: true,
      status: 200,
      json: async () => ({ data, total }),
    } as unknown as Response;
  });
  return {
    fetch: fn as unknown as typeof globalThis.fetch,
    lastUrl: () => url,
  };
};

describe("restProvider.getList", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    clearTokens();
    vi.restoreAllMocks();
  });

  it("translates pagination + sort into page/per_page/sort/order and unwraps {data,total}", async () => {
    const { fetch, lastUrl } = stubList(
      [
        { id: 1, name: "A" },
        { id: 2, name: "B" },
      ],
      2,
    );
    globalThis.fetch = fetch;
    const res = await provider.getList("leads", {
      pagination: { page: 2, perPage: 25 },
      sort: { field: "updated_at", order: "ASC" },
      filter: {},
    });
    expect(res.total).toBe(2);
    expect(res.data).toHaveLength(2);
    const url = lastUrl();
    expect(url).toContain("/api/v1/leads?");
    expect(url).toContain("page=2");
    expect(url).toContain("per_page=25");
    expect(url).toContain("sort=updated_at");
    expect(url).toContain("order=ASC");
  });

  it("omits sort when the field is id (the backend default)", async () => {
    const { fetch, lastUrl } = stubList([]);
    globalThis.fetch = fetch;
    await provider.getList("leads", {
      pagination: { page: 1, perPage: 10 },
      sort: { field: "id", order: "DESC" },
      filter: {},
    });
    expect(lastUrl()).not.toContain("sort=");
  });

  it("normalizes conversation mode to lowercase for the render layer", async () => {
    const { fetch } = stubList([{ id: "c1", mode: "HUMAN" }], 1);
    globalThis.fetch = fetch;
    const res = await provider.getList("conversations", {
      pagination: { page: 1, perPage: 10 },
      sort: { field: "id", order: "DESC" },
      filter: {},
    });
    expect((res.data[0] as Record<string, unknown>).mode).toBe("human");
  });

  it("maps the knowledge_sources resource to the knowledge/documents route", async () => {
    const { fetch, lastUrl } = stubList([]);
    globalThis.fetch = fetch;
    await provider.getList("knowledge_sources", {
      pagination: { page: 1, perPage: 10 },
      sort: { field: "id", order: "DESC" },
      filter: {},
    });
    expect(lastUrl()).toContain("/api/v1/knowledge/documents?");
  });

  it("passes filter values through as query params", async () => {
    const { fetch, lastUrl } = stubList([]);
    globalThis.fetch = fetch;
    await provider.getList("leads", {
      pagination: { page: 1, perPage: 10 },
      sort: { field: "id", order: "DESC" },
      filter: { stage: "NEW", zalo_id: "z-1" },
    });
    const url = lastUrl();
    expect(url).toContain("stage=NEW");
    expect(url).toContain("zalo_id=z-1");
  });
});

describe("restProvider custom conversation actions", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    clearTokens();
    vi.restoreAllMocks();
  });

  it("maps semi-auto mode to the semi-auto action route", async () => {
    let url = "";
    const fetch = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      url = typeof input === "string" ? input : (input as URL).toString();
      return {
        ok: true,
        status: 200,
        json: async () => ({ id: "c1", mode: "SEMI_AUTO" }),
      } as unknown as Response;
    });
    globalThis.fetch = fetch as unknown as typeof globalThis.fetch;

    const res = await provider.setConversationMode("c1", "semi_auto");

    expect(url).toContain("/api/v1/conversations/c1/semi-auto");
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/conversations/c1/semi-auto"),
      expect.objectContaining({ method: "POST" }),
    );
    expect((res as Record<string, unknown>).mode).toBe("semi_auto");
  });

  it("deletes a conversation through its dedicated REST record route", async () => {
    let url = "";
    const fetch = vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      url = typeof input === "string" ? input : (input as URL).toString();
      return {
        ok: true,
        status: 204,
        json: async () => undefined,
      } as unknown as Response;
    });
    globalThis.fetch = fetch as unknown as typeof globalThis.fetch;

    await provider.delete("conversations", {
      id: "conversation-1",
      previousData: { id: "conversation-1" },
    });

    expect(url).toContain("/api/v1/conversations/conversation-1");
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/conversations/conversation-1"),
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});

describe("legacy configuration migration oracle", () => {
  it("does not expose browser-local business configuration methods", () => {
    expect("getConfiguration" in provider).toBe(false);
    expect("updateConfiguration" in provider).toBe(false);
  });
});
