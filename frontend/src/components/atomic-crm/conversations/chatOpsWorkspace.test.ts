import { describe, expect, it, beforeEach } from "vitest";
import type { Conversation, Lead } from "../types";
import {
  deriveSystemTags,
  getAiAssistInsights,
  readActiveWorkspaceFilter,
  readSavedViews,
  saveWorkspaceView,
} from "./chatOpsWorkspace";

const makeLead = (patch: Partial<Lead> = {}): Lead =>
  ({
    id: 1,
    zalo_id: "zalo-1",
    name: "An",
    phone: "",
    desired_job: "",
    expected_salary: "",
    lead_score: null,
    lead_stage: "NEW",
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    ...patch,
  }) as Lead;

const makeConversation = (patch: Partial<Conversation> = {}): Conversation =>
  ({
    id: "conv-1",
    zalo_chat_id: "zalo-1",
    mode: "bot",
    needs_human: false,
    assigned_recruiter_id: null,
    last_inbound_at: null,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    ...patch,
  }) as Conversation;

describe("chatOpsWorkspace", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("derives operational tags from lead and conversation state", () => {
    const tags = deriveSystemTags(
      makeLead({
        phone: "0909000000",
        lead_score: "not_interested",
        lead_stage: "SKIPPED",
        next_action_at: "2026-01-02T09:00:00.000Z",
      }),
      makeConversation({ mode: "human" }),
    );

    expect(tags).toEqual(
      expect.arrayContaining([
        "has_phone",
        "needs_follow_up",
        "not_interested",
        "needs_human",
      ]),
    );
  });

  it("persists saved filter views locally", () => {
    expect(readActiveWorkspaceFilter()).toBe("all");
    saveWorkspaceView("missing_phone", "Thiếu SĐT");
    expect(
      readSavedViews().some((view) => view.filter === "missing_phone"),
    ).toBe(true);
  });

  it("prioritizes phone capture in recruiter assist when missing", () => {
    const assist = getAiAssistInsights(makeLead(), makeConversation());

    expect(assist.missing).toContain("số điện thoại");
    expect(assist.reply).toContain("số điện thoại");
    expect(assist.nextAction).toContain("Xin số điện thoại");
  });
});
