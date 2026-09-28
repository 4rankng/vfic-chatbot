import { describe, expect, it } from "vitest";

import { leadFilterFor } from "./leadLookupKey";

describe("conversation lead lookup key", () => {
  // The panel reaches a candidate's lead by one of two keys. A Zalo/OA thread
  // keeps the exact request it always made; a Messenger thread has no
  // zalo_chat_id at all, so the contact filter is the only path to its lead.
  it("keeps zalo_id first, so every Zalo and OA thread is unchanged", () => {
    expect(leadFilterFor("oa:user-1234", "contact-1")).toEqual({
      zalo_id: "oa:user-1234",
    });
  });

  it("falls back to contact_id for a Messenger thread", () => {
    expect(leadFilterFor(null, "contact-1")).toEqual({
      contact_id: "contact-1",
    });
  });

  it("falls back to contact_id when zalo_chat_id is an empty string", () => {
    expect(leadFilterFor("", "contact-1")).toEqual({
      contact_id: "contact-1",
    });
  });

  it("requests no filter when the thread carries neither key", () => {
    expect(leadFilterFor(null, null)).toEqual({});
  });
});
