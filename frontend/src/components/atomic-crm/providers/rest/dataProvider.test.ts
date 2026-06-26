import { afterEach, describe, expect, it, vi } from "vitest";

import { clearTokens } from "./api";
import { getDataProvider } from "./dataProvider";

/**
 * The REST dataProvider had zero tests. These cover the query-translation
 * contract that every react-admin <List> depends on: page/per_page/sort/order
 * mapping, the id-sort skip, conversation mode normalization, and the
 * knowledge_sources -> knowledge/documents path alias.
 */
const provider = getDataProvider();

const lastUrl = (): string => {
  const calls = vi.mocked(globalThis.fetch).mock.calls;
  const input = calls[calls.length - 1]?.[0];
  return typeof input === "string" ? input : (input as URL | Request).toString();
};

const stubEnvelope = (data: unknown[], total = data.length): typeof globalThis.fetch =>
  ((async (): Promise<Response> => ({
    ok: true,
    status: 200,
    json: async () => ({ data, total }),
  })) as unknown) as typeof globalThis.fetch;

describe("restProvider.getList", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    clearTokens();
    vi.restoreAllMocks();
  });

  it("translates pagination + sort into page/per_page/sort/order and unwraps {data,total}", async () => {
    globalThis.fetch = stubEnvelope([{ id: 1, name: "A" }, { id: 2, name: "B" }], 2);
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
    globalThis.fetch = stubEnvelope([]);
    await provider.getList("leads", {
      pagination: { page: 1, perPage: 10 },
      sort: { field: "id", order: "DESC" },
      filter: {},
    });
    expect(lastUrl()).not.toContain("sort=");
  });

  it("normalizes conversation mode to lowercase for the render layer", async () => {
    globalThis.fetch = stubEnvelope([{ id: "c1", mode: "HUMAN" }], 1);
    const res = await provider.getList("conversations", {
      pagination: { page: 1, perPage: 10 },
      sort: { field: "id", order: "DESC" },
      filter: {},
    });
    expect((res.data[0] as Record<string, unknown>).mode).toBe("human");
  });

  it("maps the knowledge_sources resource to the knowledge/documents route", async () => {
    globalThis.fetch = stubEnvelope([]);
    await provider.getList("knowledge_sources", {
      pagination: { page: 1, perPage: 10 },
      sort: { field: "id", order: "DESC" },
      filter: {},
    });
    expect(lastUrl()).toContain("/api/v1/knowledge/documents?");
  });

  it("passes filter values through as query params", async () => {
    globalThis.fetch = stubEnvelope([]);
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
