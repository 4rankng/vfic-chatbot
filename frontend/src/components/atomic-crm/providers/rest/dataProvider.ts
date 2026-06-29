import {
  type DataProvider,
  type CreateParams,
  type DeleteManyParams,
  type DeleteParams,
  type GetListParams,
  type GetManyParams,
  type GetManyReferenceParams,
  type GetOneParams,
  type Identifier,
  type UpdateManyParams,
  type UpdateParams,
} from "ra-core";
import type { ConfigurationContextValue } from "../../root/ConfigurationContext";
import { getIsInitialized } from "./authProvider";
import { apiJson, ApiError } from "./api";
import { sendHumanReply } from "@/lib/vfic/humanReplyService";

// REST dataProvider (replaces ra-supabase-core / PostgREST).
//
// Standard react-admin verbs map onto /api/v1/{resource} with the backend's
// `{ data, total }` list envelope. The backend is keyed on each resource's
// natural id (UUID for conversations/users, int for leads/jobs), so the
// users->profiles alias is gone. VFIC-specific custom methods (takeover,
// release, mark-as-read, recruiter reply, user provisioning) target the
// dedicated action routes and are re-keyed on the conversation UUID id (the
// react-admin record identity), not the legacy zalo_chat_id.

const BASE = "/api/v1";

// Some CRM resources keep their legacy react-admin name but target a backend
// route whose path differs (the name is unchanged so existing List/Show
// registrations and <Resource name=...> still resolve). Map resource -> backend
// path segment here.
const RESOURCE_PATH: Record<string, string> = {
  knowledge_sources: "knowledge/documents",
  projects: "knowledge/projects",
  personas: "knowledge/personas",
};

const pathFor = (resource: string): string =>
  `${BASE}/${RESOURCE_PATH[resource] ?? resource}`;
const onePath = (resource: string, id: Identifier): string =>
  `${pathFor(resource)}/${encodeURIComponent(String(id))}`;

type ApiRecord = Record<string, unknown>;
interface ListEnvelope {
  data: ApiRecord[];
  total: number;
}

// Backend enums are uppercase; the CRM render layer reads lowercase mode values
// (`=== "bot"` / `=== "human"`). Normalise conversation records so those checks
// still hold. CLOSED maps to "closed" (falls through bot/human branches).
const normalize = (resource: string, record: ApiRecord): ApiRecord => {
  if (resource === "conversations" && typeof record.mode === "string") {
    return { ...record, mode: (record.mode as string).toLowerCase() };
  }
  // bot_runs.outcome arrives uppercase from the backend enum; the CRM's
  // outcomeMeta table is keyed lowercase (sent/suppressed/error).
  if (resource === "bot_runs" && typeof record.outcome === "string") {
    return { ...record, outcome: (record.outcome as string).toLowerCase() };
  }
  return record;
};

// Marshals backend JSON into a react-admin record. Returned as `any` because
// the DataProvider methods are generic over `RecordType extends RaRecord`, and a
// concrete `RaRecord[]` is not assignable to an invariant `RecordType[]`. This
// matches react-admin's own loosely-typed provider seam.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const toRec = (resource: string, record: ApiRecord): any =>
  normalize(resource, record);

const buildListQuery = (
  params: GetListParams | GetManyReferenceParams,
  resource?: string,
): string => {
  const sp = new URLSearchParams();
  const pagination = params.pagination ?? { page: 1, perPage: 25 };
  sp.set("page", String(pagination.page ?? 1));
  sp.set("per_page", String(pagination.perPage ?? 25));

  const sort = params.sort;
  if (sort?.field && sort.field !== "id") {
    sp.set("sort", sort.field);
    sp.set("order", (sort.order ?? "DESC").toUpperCase());
  }

  const filter = (params.filter ?? {}) as Record<string, unknown>;
  for (const [key, value] of Object.entries(filter)) {
    if (value === undefined || value === null || value === "") continue;
    // ra filter keys pass straight through as query params; the backend honours
    // the ones it knows (mode/status/zalo_chat_id/needs_attention on
    // conversations; stage/zalo_id/zalo_ids on leads) and ignores the rest.
    const wireValue =
      resource === "conversations" && (key === "mode" || key === "status")
        ? String(value).toUpperCase()
        : Array.isArray(value)
          ? value.join(",")
          : String(value);
    sp.set(key, wireValue);
  }
  return sp.toString();
};

const restProvider: DataProvider = {
  async getList(resource: string, params: GetListParams) {
    const body = await apiJson<ListEnvelope>(
      `${pathFor(resource)}?${buildListQuery(params, resource)}`,
    );
    return {
      data: body.data.map((r) => toRec(resource, r)),
      total: body.total,
    };
  },

  async getOne(resource: string, params: GetOneParams) {
    const record = await apiJson<ApiRecord>(onePath(resource, params.id));
    return { data: toRec(resource, record) };
  },

  async getMany(resource: string, params: GetManyParams) {
    // No batch-by-id endpoint; fan out getOne per id (bounded N, small).
    const rows = await Promise.all(
      params.ids.map((id) =>
        apiJson<ApiRecord>(onePath(resource, id)).catch(() => null),
      ),
    );
    return {
      data: rows
        .filter((r): r is ApiRecord => r !== null)
        .map((r) => toRec(resource, r)),
    };
  },

  async getManyReference(resource: string, params: GetManyReferenceParams) {
    // ReferenceManyField filters by { [target]: id }; fold it into the filter.
    const merged: GetManyReferenceParams = {
      ...params,
      filter: { ...params.filter, [params.target]: params.id },
    };
    const body = await apiJson<ListEnvelope>(
      `${pathFor(resource)}?${buildListQuery(merged, resource)}`,
    );
    return {
      data: body.data.map((r) => toRec(resource, r)),
      total: body.total,
    };
  },

  async create(resource: string, params: CreateParams) {
    const record = await apiJson<ApiRecord>(pathFor(resource), {
      method: "POST",
      body: params.data as Record<string, unknown>,
    });
    return { data: toRec(resource, record) };
  },

  async update(resource: string, params: UpdateParams) {
    const record = await apiJson<ApiRecord>(onePath(resource, params.id), {
      method: "PATCH",
      body: params.data as Record<string, unknown>,
    });
    return { data: toRec(resource, record) };
  },

  async updateMany(resource: string, params: UpdateManyParams) {
    const ids = await Promise.all(
      params.ids.map((id) =>
        apiJson<ApiRecord>(onePath(resource, id), {
          method: "PATCH",
          body: params.data as Record<string, unknown>,
        })
          .then(() => id)
          .catch(() => null),
      ),
    );
    return { data: ids.filter((id): id is Identifier => id !== null) };
  },

  async delete(resource: string, params: DeleteParams) {
    await apiJson<void>(onePath(resource, params.id), { method: "DELETE" });
    // Backend user-deletion is intentionally not supported (accounts are
    // disabled, not removed); when the route 405s the previous record is
    // returned so the optimistic UI still settles.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return { data: (params.previousData ?? { id: params.id }) as any };
  },

  async deleteMany(resource: string, params: DeleteManyParams) {
    await Promise.all(
      params.ids.map((id) =>
        apiJson<void>(onePath(resource, id), { method: "DELETE" }).catch(
          () => null,
        ),
      ),
    );
    return { data: params.ids };
  },
};

const getDataProviderWithCustomMethods = () => ({
  ...restProvider,

  async isInitialized() {
    return getIsInitialized();
  },

  // VFIC has no configuration table; configuration is app-defined (seeded from
  // <CRM> props). Return empty so useConfigurationLoader keeps the defaults
  // instead of erroring against a missing endpoint on every load.
  async getConfiguration(): Promise<ConfigurationContextValue> {
    return {} as ConfigurationContextValue;
  },

  // No-op: VFIC has no configuration endpoint to write to. Kept to satisfy the
  // data-provider interface (useConfigurationLoader invokes it on saves).
  async updateConfiguration(
    config: ConfigurationContextValue,
  ): Promise<ConfigurationContextValue> {
    return config;
  },

  // Recruiter reply: ownership is established by the Bearer JWT (the backend
  // verifies the caller owns the conversation and mode=HUMAN). The body carries
  // only the message text — no recruiter_id — closing the spoof vector.
  // `conversationId` is the conversation UUID (react-admin record id).
  async sendHumanReply(conversationId: string, message: string) {
    await sendHumanReply({ conversationId, message });
  },

  async takeOverConversation(conversationId: string) {
    return apiJson<ApiRecord>(
      `${BASE}/conversations/${encodeURIComponent(conversationId)}/take-over`,
      { method: "POST" },
    ).then((r) => normalize("conversations", r));
  },

  async releaseConversation(conversationId: string) {
    return apiJson<ApiRecord>(
      `${BASE}/conversations/${encodeURIComponent(conversationId)}/release`,
      { method: "POST" },
    ).then((r) => normalize("conversations", r));
  },

  async setConversationMode(
    conversationId: string,
    mode: "bot" | "human" | "semi_auto",
  ) {
    const action =
      mode === "human"
        ? "take-over"
        : mode === "semi_auto"
          ? "semi-auto"
          : "release";
    return apiJson<ApiRecord>(
      `${BASE}/conversations/${encodeURIComponent(conversationId)}/${action}`,
      { method: "POST" },
    ).then((r) => normalize("conversations", r));
  },

  // Reset unread_count to 0. Returns the updated conversation (callers refresh).
  async markAsRead(conversationId: string) {
    return apiJson<ApiRecord>(
      `${BASE}/conversations/${encodeURIComponent(conversationId)}/read`,
      { method: "POST" },
    ).then((r) => normalize("conversations", r));
  },

  // Admin user provisioning (replaces the vfic_create_user edge function).
  async createProfile(body: Record<string, unknown>) {
    return apiJson<ApiRecord>(`${BASE}/users`, { method: "POST", body });
  },

  async disableUser(userId: string) {
    return apiJson<ApiRecord>(`${BASE}/users/${encodeURIComponent(userId)}/disable`, {
      method: "POST",
    });
  },

  async enableUser(userId: string) {
    return apiJson<ApiRecord>(`${BASE}/users/${encodeURIComponent(userId)}/enable`, {
      method: "POST",
    });
  },

  // Sign-up is disabled. VFIC accounts are provisioned out-of-band by an admin.
  async signUp(_body: {
    email: string;
    password: string;
    first_name: string;
    last_name: string;
  }): Promise<{ user: null; session: null }> {
    throw new ApiError(403, "Sign-up is disabled.");
  },
});

export type CrmDataProvider = ReturnType<
  typeof getDataProviderWithCustomMethods
>;

export const getDataProvider = (): CrmDataProvider =>
  getDataProviderWithCustomMethods();
