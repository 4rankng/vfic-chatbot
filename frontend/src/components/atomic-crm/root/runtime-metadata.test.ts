import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { PublicRuntimeManifest } from "../installation/runtime-manifest";
import { applyRuntimeMetadata, resetRuntimeMetadata } from "./runtime-metadata";

const checksum = "a".repeat(64);

const activeManifest = (overrides: Record<string, unknown> = {}) =>
  ({
    schema_version: 1,
    lifecycle: "ACTIVE",
    authority_generation: 1,
    revision_id: "00000000-0000-4000-8000-000000000001",
    manifest_checksum: checksum,
    pack_key: "recruitment",
    pack_version: "1.0.0",
    pack_contract_hash: checksum,
    customer_identity: { display_name: "Công ty Hoa Sen" },
    branding: {
      app_name: "Cổng Hoa Sen",
      logo_url: null,
      favicon_url: null,
      primary_color: "#1255AA",
      secondary_color: null,
    },
    locale: "vi-VN",
    timezone: "Asia/Ho_Chi_Minh",
    currency: "VND",
    terminology: {},
    capability_ids: ["recruitment.conversations"],
    readiness_code: "READY",
    ...overrides,
  }) as unknown as PublicRuntimeManifest;

const ensureMeta = (
  selector: string,
  attributes: Record<string, string>,
): HTMLMetaElement => {
  const current = document.head.querySelector<HTMLMetaElement>(selector);
  const element = current ?? document.createElement("meta");
  for (const [name, value] of Object.entries(attributes)) {
    element.setAttribute(name, value);
  }
  if (!current) document.head.append(element);
  return element;
};

const metadataContent = (selector: string): string =>
  document.head.querySelector<HTMLMetaElement>(selector)?.content ?? "";

describe("runtime metadata", () => {
  beforeEach(() => {
    document.title = "Khách hàng cũ";
    document.documentElement.lang = "en";
    ensureMeta('meta[name="theme-color"]', {
      name: "theme-color",
      content: "#FF0000",
    });
    ensureMeta('meta[name="description"]', {
      name: "description",
      content: "Mô tả cũ",
    });
    ensureMeta('meta[property="og:title"]', {
      property: "og:title",
      content: "OG cũ",
    });
    ensureMeta('meta[property="og:description"]', {
      property: "og:description",
      content: "OG mô tả cũ",
    });
    ensureMeta('meta[name="twitter:title"]', {
      name: "twitter:title",
      content: "Twitter cũ",
    });
    ensureMeta('meta[name="twitter:description"]', {
      name: "twitter:description",
      content: "Twitter mô tả cũ",
    });
    const favicon = document.createElement("link");
    favicon.rel = "icon";
    favicon.href = "/old-customer.png";
    favicon.dataset.runtimeMetadata = "favicon";
    document.head.append(favicon);
  });

  afterEach(() => {
    resetRuntimeMetadata();
    document.head
      .querySelectorAll('[data-runtime-metadata="favicon"]')
      .forEach((element) => element.remove());
  });

  it("resets every customer-controlled metadata surface to TingHire", () => {
    resetRuntimeMetadata();

    expect(document.title).toBe("TingHire");
    expect(document.documentElement.lang).toBe("vi");
    expect(metadataContent('meta[name="theme-color"]')).toBe("#172033");
    expect(metadataContent('meta[name="description"]')).toContain("TingHire");
    expect(metadataContent('meta[property="og:title"]')).toBe("TingHire");
    expect(metadataContent('meta[property="og:description"]')).toBe(
      "Tuyển đúng người. Nhanh hơn.",
    );
    expect(metadataContent('meta[name="twitter:title"]')).toBe("TingHire");
    expect(metadataContent('meta[name="twitter:description"]')).toBe(
      "Tuyển đúng người. Nhanh hơn.",
    );
    expect(
      document.head.querySelector('[data-runtime-metadata="favicon"]'),
    ).toBeNull();
  });

  it("applies only configured fields from an ACTIVE manifest", () => {
    applyRuntimeMetadata(activeManifest());

    expect(document.title).toBe("Cổng Hoa Sen · TingHire");
    expect(document.documentElement.lang).toBe("vi-VN");
    expect(metadataContent('meta[name="theme-color"]')).toBe("#172033");
    expect(metadataContent('meta[name="description"]')).toContain("TingHire");
    expect(metadataContent('meta[property="og:title"]')).toBe("TingHire");
    expect(metadataContent('meta[name="twitter:title"]')).toBe("TingHire");
    expect(
      document.head.querySelector('[data-runtime-metadata="favicon"]'),
    ).toBeNull();
  });

  it("uses display name only when no configured app name exists", () => {
    applyRuntimeMetadata(
      activeManifest({
        branding: {
          app_name: null,
          logo_url: null,
          favicon_url: null,
          primary_color: null,
          secondary_color: null,
        },
      }),
    );

    expect(document.title).toBe("Công ty Hoa Sen · TingHire");
    expect(metadataContent('meta[name="theme-color"]')).toBe("#172033");
  });

  it("refuses to apply draft branding and leaves a neutral document", () => {
    applyRuntimeMetadata(
      activeManifest({
        lifecycle: "DRAFT",
        revision_id: null,
        manifest_checksum: null,
        pack_key: null,
        pack_version: null,
        pack_contract_hash: null,
      }),
    );

    expect(document.title).toBe("TingHire");
    expect(document.documentElement.lang).toBe("vi");
    expect(metadataContent('meta[name="theme-color"]')).toBe("#172033");
  });

  it("clears the previous customer before applying a new active customer", () => {
    applyRuntimeMetadata(
      activeManifest({
        branding: {
          app_name: "Khách hàng A",
          logo_url: null,
          favicon_url: "/customer-a.png",
          primary_color: "#AA0000",
          secondary_color: null,
        },
      }),
    );
    resetRuntimeMetadata();
    applyRuntimeMetadata(
      activeManifest({
        customer_identity: { display_name: "Khách hàng B" },
        branding: {
          app_name: null,
          logo_url: null,
          favicon_url: null,
          primary_color: null,
          secondary_color: null,
        },
        locale: "en-US",
      }),
    );

    expect(document.title).toBe("Khách hàng B · TingHire");
    expect(document.documentElement.lang).toBe("en-US");
    expect(metadataContent('meta[name="theme-color"]')).toBe("#172033");
    expect(document.head.textContent).not.toContain("Khách hàng A");
    expect(document.head.innerHTML).not.toContain("customer-a.png");
  });
});
