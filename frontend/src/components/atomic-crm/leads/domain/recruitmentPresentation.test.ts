import { describe, expect, it } from "vitest";

import type { Lead } from "../../types";
import {
  buildRecruitmentContextIdentity,
  buildRecruitmentRowPresentation,
} from "./recruitmentPresentation";

// A candidate whose channel nickname and confirmed name both exist, and who
// has a different photo on each — the only input that can tell the two
// precedences apart.
const lead: Lead = {
  id: 1,
  zalo_id: "oa:user-1",
  name: "Nguyễn Văn An",
  phone: "0900000001",
  desired_job: "Tài xế",
  expected_salary: "",
  lead_score: "warm",
  lead_stage: "NEW",
  avatar_url: "https://example.test/lead.jpg",
  created_at: "2026-09-14T00:00:00Z",
  updated_at: "2026-09-14T00:00:00Z",
};

type ProfileSource = Parameters<typeof buildRecruitmentRowPresentation>[0];

const oaConversation: ProfileSource = {
  zalo_channel: "oa",
  zalo_chat_id: "oa:user-1",
  contact: {
    id: "contact-1",
    display_name: "Bé Gấu",
    avatar_url: "https://example.test/channel.jpg",
  },
};

const messengerConversation: ProfileSource = {
  zalo_channel: "bot",
  zalo_chat_id: null,
  contact: {
    id: "contact-2",
    display_name: "Frank Ng",
    avatar_url: "https://example.test/messenger.jpg",
  },
  channel_identity: {
    id: "identity-2",
    provider: "facebook_messenger",
    account_key: "page-1",
    external_id: "psid-987654",
  },
};

// The inbox list and the thread header label the same conversation differently
// ON PURPOSE. The list leads with the recruiter-confirmed identity because
// recruiters scan it to find a candidate; the header leads with the identity
// the candidate presents on that channel and demotes the confirmed name to the
// subtitle. The rationale is recorded in capabilities/recruitment/index.tsx.
// These tests exist so the mismatch reads as a decision rather than a defect,
// and so nobody collapses the two into "consistency" by accident.
describe("list and thread-header identity precedence diverge deliberately", () => {
  it("leads the list row with the confirmed candidate, photo included", () => {
    const row = buildRecruitmentRowPresentation(oaConversation, lead);

    expect(row.displayName).toBe("Nguyễn Văn An");
    expect(row.avatarUrl).toBe("https://example.test/lead.jpg");
  });

  it("leads the thread header with the channel profile, photo included", () => {
    const identity = buildRecruitmentContextIdentity(oaConversation, lead);

    expect(identity.displayName).toBe("Bé Gấu");
    expect(identity.avatarUrl).toBe("https://example.test/channel.jpg");
    // The confirmed name is demoted, never dropped.
    expect(identity.secondaryName).toBe("Nguyễn Văn An");
    expect(identity.phone).toBe("0900000001");
  });

  it("applies the same split to Messenger, not just Zalo OA", () => {
    expect(
      buildRecruitmentRowPresentation(messengerConversation, lead),
    ).toMatchObject({
      displayName: "Nguyễn Văn An",
      avatarUrl: "https://example.test/lead.jpg",
    });
    expect(
      buildRecruitmentContextIdentity(messengerConversation, lead),
    ).toMatchObject({
      displayName: "Frank Ng",
      avatarUrl: "https://example.test/messenger.jpg",
      secondaryName: "Nguyễn Văn An",
    });
  });

  it("agrees on both surfaces once there is only one identity to show", () => {
    // No lead record: nothing to disagree about, so the channel profile is the
    // candidate on every surface and no subtitle is manufactured.
    const row = buildRecruitmentRowPresentation(oaConversation, undefined);
    const identity = buildRecruitmentContextIdentity(oaConversation, undefined);

    expect(row.displayName).toBe("Bé Gấu");
    expect(identity.displayName).toBe("Bé Gấu");
    expect(row.avatarUrl).toBe(identity.avatarUrl);
    expect(identity.secondaryName).toBeUndefined();
  });

  it("keeps name and photo describing one identity when a channel photo is missing", () => {
    // Channel name but no channel photo: the header still leads with the
    // channel name and falls back to the lead photo rather than showing none.
    const identity = buildRecruitmentContextIdentity(
      {
        ...oaConversation,
        contact: { id: "contact-1", display_name: "Bé Gấu", avatar_url: null },
      },
      lead,
    );

    expect(identity.displayName).toBe("Bé Gấu");
    expect(identity.avatarUrl).toBe("https://example.test/lead.jpg");
  });
});
