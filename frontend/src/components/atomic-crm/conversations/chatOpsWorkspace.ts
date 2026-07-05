import type {
  Conversation,
  Lead,
  LeadAssist,
  LeadChatOpsActionResult,
  LeadSignal,
  LeadTag,
} from "../types";
import { apiJson } from "../providers/rest/api";

export type OperationalTagKey =
  | "has_phone"
  | "missing_phone"
  | "needs_follow_up"
  | "not_interested"
  | "registered"
  | "salary_missing"
  | "location_missing"
  | "needs_human";

export type ManualLeadTagInput = {
  key: string;
  label: string;
  tone?: "good" | "warn" | "danger" | "info";
};

export type WorkspaceFilterKey =
  | "all"
  | "needs_attention"
  | "has_phone"
  | "missing_phone"
  | "follow_up"
  | "not_interested"
  | "human"
  | "semi_auto"
  | "bot";

export type SavedWorkspaceView = {
  id: string;
  label: string;
  filter: WorkspaceFilterKey;
};

export const TAG_STORAGE_EVENT = "vfic:chatops-tags-updated";
export const VIEWS_STORAGE_EVENT = "vfic:chatops-views-updated";

const VIEWS_STORAGE_KEY = "vfic:chatops:saved-views:v1";
const ACTIVE_VIEW_STORAGE_KEY = "vfic:chatops:active-filter:v1";
const RECENT_TAGS_STORAGE_KEY = "vfic:chatops:recent-tags:v1";

export const OPERATIONAL_TAGS: Array<{
  key: OperationalTagKey;
  label: string;
  tone: "good" | "warn" | "danger" | "info";
  system?: boolean;
}> = [
  { key: "has_phone", label: "Có SĐT", tone: "good", system: true },
  { key: "missing_phone", label: "Thiếu SĐT", tone: "warn", system: true },
  { key: "needs_follow_up", label: "Cần follow-up", tone: "info" },
  { key: "not_interested", label: "Không quan tâm", tone: "danger" },
  { key: "registered", label: "Đã đăng ký", tone: "good" },
  { key: "salary_missing", label: "Thiếu lương", tone: "warn" },
  { key: "location_missing", label: "Thiếu khu vực", tone: "warn" },
  { key: "needs_human", label: "Cần người xử lý", tone: "danger" },
];

const DEFAULT_SAVED_VIEWS: SavedWorkspaceView[] = [
  { id: "needs_attention", label: "Cần trả lời", filter: "needs_attention" },
  { id: "missing_phone", label: "Thiếu SĐT", filter: "missing_phone" },
  { id: "follow_up", label: "Follow-up", filter: "follow_up" },
];

const canUseStorage = () =>
  typeof window !== "undefined" && typeof window.localStorage !== "undefined";

const readJson = <T>(key: string, fallback: T): T => {
  if (!canUseStorage()) return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
};

const writeJson = (key: string, value: unknown, eventName: string) => {
  if (!canUseStorage()) return;
  window.localStorage.setItem(key, JSON.stringify(value));
  window.dispatchEvent(new Event(eventName));
};

export const deriveSystemTags = (
  lead?: Lead | null,
  conversation?: Conversation | null,
): OperationalTagKey[] => {
  const tags: OperationalTagKey[] = [];
  if (!lead) return tags;
  if (lead.phone?.trim()) tags.push("has_phone");
  else tags.push("missing_phone");
  if (lead.next_action_at) tags.push("needs_follow_up");
  if (lead.lead_score === "not_interested" || lead.lead_stage === "SKIPPED") {
    tags.push("not_interested");
  }
  if (lead.lead_stage === "REGISTERED") tags.push("registered");
  if (!lead.expected_salary?.trim()) tags.push("salary_missing");
  if (!lead.region?.trim() && !lead.living_area?.trim()) {
    tags.push("location_missing");
  }
  if (conversation?.needs_human || conversation?.mode === "human") {
    tags.push("needs_human");
  }
  return tags;
};

export const getTagMeta = (key: OperationalTagKey) =>
  OPERATIONAL_TAGS.find((tag) => tag.key === key) ?? {
    key,
    label: key,
    tone: "info" as const,
  };

export const readSavedViews = (): SavedWorkspaceView[] => {
  const saved = readJson<SavedWorkspaceView[]>(VIEWS_STORAGE_KEY, []);
  return saved.length > 0 ? saved : DEFAULT_SAVED_VIEWS;
};

export const saveWorkspaceView = (
  filter: WorkspaceFilterKey,
  label: string,
) => {
  const next = [
    ...readSavedViews().filter((view) => view.filter !== filter),
    { id: `${filter}-${Date.now()}`, label, filter },
  ].slice(-6);
  writeJson(VIEWS_STORAGE_KEY, next, VIEWS_STORAGE_EVENT);
};

export const readActiveWorkspaceFilter = (): WorkspaceFilterKey =>
  readJson<WorkspaceFilterKey>(ACTIVE_VIEW_STORAGE_KEY, "all");

export const persistActiveWorkspaceFilter = (filter: WorkspaceFilterKey) => {
  if (!canUseStorage()) return;
  window.localStorage.setItem(ACTIVE_VIEW_STORAGE_KEY, filter);
};

export const readRecentLeadTags = (): ManualLeadTagInput[] =>
  readJson<ManualLeadTagInput[]>(RECENT_TAGS_STORAGE_KEY, []);

export const rememberRecentLeadTags = (tags: ManualLeadTagInput[]) => {
  const current = readRecentLeadTags();
  const byKey = new Map<string, ManualLeadTagInput>();
  for (const tag of [...tags, ...current]) {
    const label = tag.label.trim();
    if (!label) continue;
    byKey.set(tag.key, {
      key: tag.key,
      label,
      tone: tag.tone ?? "info",
    });
  }
  writeJson(
    RECENT_TAGS_STORAGE_KEY,
    Array.from(byKey.values()).slice(0, 8),
    TAG_STORAGE_EVENT,
  );
};

export const getMissingFields = (lead?: Lead | null) => {
  if (!lead) return ["hồ sơ ứng viên"];
  const fields: string[] = [];
  if (!lead.name?.trim()) fields.push("tên");
  if (!lead.phone?.trim()) fields.push("số điện thoại");
  if (!lead.desired_job?.trim()) fields.push("vị trí mong muốn");
  if (!lead.region?.trim() && !lead.living_area?.trim()) fields.push("khu vực");
  if (!lead.expected_salary?.trim()) fields.push("mức lương mong muốn");
  return fields;
};

export const getAiAssistInsights = (
  lead?: Lead | null,
  conversation?: Conversation | null,
) => {
  const missing = getMissingFields(lead);
  const mode = conversation?.mode ?? "bot";
  const summary =
    lead?.lead_score === "not_interested"
      ? "Ứng viên đã thể hiện không quan tâm. Không nên tiếp tục nhắn chủ động trừ khi có tín hiệu mới."
      : lead?.phone
        ? "Ứng viên đã có số điện thoại. Ưu tiên xác nhận nhu cầu, khu vực và chuyển sang bước đăng ký."
        : "Ứng viên chưa có số điện thoại. Ưu tiên xin thông tin liên hệ trước khi để bot tư vấn dài.";
  const reply =
    missing.length > 0
      ? `Mình hỗ trợ bạn nhanh hơn nếu bạn cho mình ${missing.slice(0, 2).join(" và ")} nhé.`
      : "Mình đã có đủ thông tin chính. Bạn muốn mình chuyển hồ sơ để tư vấn viên gọi xác nhận không?";
  const nextAction = lead?.next_action_at
    ? "Đã có lịch follow-up. Kiểm tra lại trước khi gửi thêm tin."
    : lead?.phone
      ? "Đặt follow-up gần nhất và chuyển ứng viên sang Đang liên hệ."
      : "Xin số điện thoại, sau đó tạo follow-up nếu ứng viên phản hồi.";

  return {
    summary,
    missing,
    reply,
    nextAction,
    modeLabel:
      mode === "human"
        ? "Người xử lý"
        : mode === "semi_auto"
          ? "Bán tự động"
          : "Chatbot",
  };
};

export const getAutomationRecipes = (
  lead?: Lead | null,
  conversation?: Conversation | null,
): LeadSignal[] => [
  {
    key: "phone",
    name: "Số điện thoại",
    status: lead?.phone ? "Đã có thể liên hệ" : "Chưa có dữ liệu",
    active: Boolean(lead?.phone),
    action: lead?.phone ? "mark_contacting" : null,
  },
  {
    key: "not_interested",
    name: "Không quan tâm",
    status:
      lead?.lead_score === "not_interested" || lead?.lead_stage === "SKIPPED"
        ? "Nên dừng follow-up"
        : "Chưa có tín hiệu",
    active:
      lead?.lead_score === "not_interested" || lead?.lead_stage === "SKIPPED",
    action:
      lead?.lead_score === "not_interested" || lead?.lead_stage === "SKIPPED"
        ? null
        : "mark_not_interested",
  },
  {
    key: "followup",
    name: "Follow-up",
    status: lead?.next_action_at ? "Đã có lịch" : "Nên đặt lịch",
    active: Boolean(lead?.next_action_at),
    action: lead?.next_action_at ? null : "schedule_followup",
  },
  {
    key: "human",
    name: "Cần người xử lý",
    status:
      conversation?.needs_human || conversation?.mode === "human"
        ? "Đang ưu tiên"
        : "Theo dõi",
    active: Boolean(
      conversation?.needs_human || conversation?.mode === "human",
    ),
    action: null,
  },
];

export const fetchLeadTags = (leadId: number | string) =>
  apiJson<LeadTag[]>(`/api/v1/leads/${leadId}/tags`);

export const saveLeadTags = (
  leadId: number | string,
  tags: ManualLeadTagInput[],
) =>
  apiJson<LeadTag[]>(`/api/v1/leads/${leadId}/tags`, {
    method: "PUT",
    body: { tags },
  });

export const fetchLeadAssist = (leadId: number | string) =>
  apiJson<LeadAssist>(`/api/v1/leads/${leadId}/assist`);

export const runLeadChatOpsAction = (leadId: number | string, action: string) =>
  apiJson<LeadChatOpsActionResult>(
    `/api/v1/leads/${leadId}/chatops-actions/${action}`,
    { method: "POST" },
  );

export const dispatchLeadTagsUpdated = (leadId: number | string) => {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent(TAG_STORAGE_EVENT, { detail: { lead_id: leadId } }),
  );
};
