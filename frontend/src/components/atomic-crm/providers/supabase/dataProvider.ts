import { supabaseDataProvider } from "ra-supabase-core";
import {
  withLifecycleCallbacks,
  type CreateParams,
  type DataProvider,
  type DeleteManyParams,
  type DeleteParams,
  type GetListParams,
  type GetManyParams,
  type GetOneParams,
  type ResourceCallbacks,
  type UpdateManyParams,
  type UpdateParams,
} from "ra-core";
import type { Session, User } from "@supabase/supabase-js";
import type { ConfigurationContextValue } from "../../root/ConfigurationContext";
import { getIsInitialized } from "./authProvider";
import { getSupabaseClient } from "./supabase";
import { vficConfig } from "@/lib/vfic/config";
import { sendHumanReply } from "@/lib/vfic/humanReplyService";

// The CRM exposes friendly resource names that differ from the underlying VFIC
// table names. The "users" resource (URL /users, menu "Users", admin-gated) is
// backed by the `profiles` table. Map each friendly resource to its real table
// for every CRUD verb so the data layer queries the right PostgREST endpoint.
// (ra-supabase-core / ra-data-postgrest uses the resource name as the table
// name verbatim, so without this the Users screen would 404 against live.)
const RESOURCE_TABLE_MAP: Record<string, string> = {
  users: "profiles",
};
const resolveTable = (resource: string) =>
  RESOURCE_TABLE_MAP[resource] ?? resource;

const withTableAlias = (provider: DataProvider): DataProvider => {
  return {
    ...provider,
    getList: (resource: string, params: GetListParams) =>
      provider.getList(resolveTable(resource), params),
    getOne: (resource: string, params: GetOneParams) =>
      provider.getOne(resolveTable(resource), params),
    getMany: (resource: string, params: GetManyParams) =>
      provider.getMany(resolveTable(resource), params),
    update: (resource: string, params: UpdateParams) =>
      provider.update(resolveTable(resource), params),
    updateMany: (resource: string, params: UpdateManyParams) =>
      provider.updateMany(resolveTable(resource), params),
    create: (resource: string, params: CreateParams) =>
      provider.create(resolveTable(resource), params),
    delete: (resource: string, params: DeleteParams) =>
      provider.delete(resolveTable(resource), params),
    deleteMany: (resource: string, params: DeleteManyParams) =>
      provider.deleteMany(resolveTable(resource), params),
  };
};

const getBaseDataProvider = () =>
  withTableAlias(
    supabaseDataProvider({
      instanceUrl: vficConfig.supabaseUrl,
      apiKey: vficConfig.supabasePublishableKey,
      supabaseClient: getSupabaseClient(),
      sortOrder: "asc,desc.nullslast" as any,
    }),
  );

const getDataProviderWithCustomMethods = () => {
  const baseDataProvider = getBaseDataProvider();

  return {
    ...baseDataProvider,
    async isInitialized() {
      return getIsInitialized();
    },
    // VFIC has no configuration table; configuration is app-defined (seeded from
    // <CRM> props in CRM.tsx). Return empty so useConfigurationLoader keeps the
    // defaults instead of 404-ing against a missing table on every load.
    async getConfiguration(): Promise<ConfigurationContextValue> {
      // Intentionally empty: callers (CRM.tsx, useConfigurationLoader) only
      // apply the result when Object.keys().length > 0, so this preserves the
      // seeded defaults without 404-ing against a missing configuration table.
      return {} as ConfigurationContextValue;
    },
    // VFIC has no configuration table. Kept as a no-op so legacy callers
    // (e.g. SettingsPage) keep typechecking without writing to a dead table.
    async updateConfiguration(
      config: ConfigurationContextValue,
    ): Promise<ConfigurationContextValue> {
      return config;
    },

    // VFIC custom methods — contracts verified against the live n8n workflow
    // (wridAhFQuct6IGoX) and the vfic_take_over / vfic_release RPCs.
    //
    // sendHumanReply delegates to humanReplyService: ownership is carried by the
    // Bearer JWT (introspected by n8n), and the body carries NO recruiter_id —
    // closing the spoof vector. Typed HumanReplyError surfaces 401/403/409 to the
    // UI. (Phase 3b will re-route this through the vfic_human_relay edge fn.)
    async sendHumanReply(zaloChatId: string, message: string) {
      await sendHumanReply({ zaloChatId, message });
    },

    async takeOverConversation(zaloChatId: string) {
      const session = await getSupabaseClient().auth.getSession();
      const recruiterId = session.data.session?.user?.id;
      if (!recruiterId) throw new Error("Not authenticated");

      const { data, error } = await getSupabaseClient().rpc("vfic_take_over", {
        p_zalo_chat_id: zaloChatId,
        p_recruiter: recruiterId,
      });
      if (error) throw new Error(error.message);
      return data;
    },

    async releaseConversation(zaloChatId: string) {
      const session = await getSupabaseClient().auth.getSession();
      const recruiterId = session.data.session?.user?.id;
      if (!recruiterId) throw new Error("Not authenticated");

      const { data, error } = await getSupabaseClient().rpc("vfic_release", {
        p_zalo_chat_id: zaloChatId,
        p_recruiter: recruiterId,
      });
      if (error) throw new Error(error.message);
      return data;
    },

    async createProfile(body: Record<string, unknown>) {
      const { data, error } = await getSupabaseClient().functions.invoke(
        "vfic_create_user",
        {
          method: "POST",
          body,
        },
      );
      if (!data || error) {
        throw new Error(error?.message || "Failed to create user");
      }
      return data;
    },

    // Sign-up is disabled. VFIC accounts are provisioned out-of-band by an
    // admin (Phase 7: vfic_admin_users edge function). This neutralises the
    // previous unauthenticated-account-creation surface (supabase.auth.signUp)
    // while preserving the method signature so the fakerest provider and the
    // legacy SignupPage typecheck.
    async signUp(_body: {
      email: string;
      password: string;
      first_name: string;
      last_name: string;
    }): Promise<{ user: User | null; session: Session | null }> {
      throw new Error("Sign-up is disabled.");
    },
  } satisfies DataProvider;
};

export type CrmDataProvider = ReturnType<
  typeof getDataProviderWithCustomMethods
>;

const lifeCycleCallbacks: ResourceCallbacks[] = [
  {
    resource: "leads",
    beforeGetList: async (params) => {
      return applyFullTextSearch(["name", "phone", "desired_job", "zalo_id"])(
        params,
      );
    },
  },
  {
    resource: "conversations",
    beforeGetList: async (params) => {
      return applyFullTextSearch(["zalo_chat_id", "assigned_recruiter_id"])(
        params,
      );
    },
  },
  {
    resource: "users",
    beforeGetList: async (params) => {
      return applyFullTextSearch(["full_name", "email"])(params);
    },
  },
];

export const getDataProvider = () => {
  return withLifecycleCallbacks(
    getDataProviderWithCustomMethods(),
    lifeCycleCallbacks,
  ) as CrmDataProvider;
};

const applyFullTextSearch = (columns: string[]) => (params: GetListParams) => {
  if (!params.filter?.q) {
    return params;
  }
  const { q, ...filter } = params.filter;
  return {
    ...params,
    filter: {
      ...filter,
      "@or": columns.reduce((acc, column) => {
        return {
          ...acc,
          [`${column}@ilike`]: q,
        };
      }, {}),
    },
  };
};
