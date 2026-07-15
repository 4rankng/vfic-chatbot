import { describe, expect, it } from "vitest";

import contacts from "./index";

describe("Contact record presentation", () => {
  it("never falls back to a raw Contact UUID", () => {
    const represent = contacts.recordRepresentation;
    expect(represent({ id: "00000000-0000-4000-8000-000000000099" })).toBe("Chưa có tên");
    expect(represent({ primary_phone: "0901234567" })).toBe("0901234567");
    expect(represent({ primary_email: "contact@example.com" })).toBe("contact@example.com");
    expect(represent({ primary_channel: { provider: "zalo" } })).toBe("zalo");
  });
});
