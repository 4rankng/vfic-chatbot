import { supabaseDataProvider } from "ra-supabase-core";
import {
  withLifecycleCallbacks,
  type DataProvider,
  type GetListParams,
  type Identifier,
  type ResourceCallbacks,
} from "ra-core";
import type { ConfigurationContextValue } from "../../root/ConfigurationContext";
import { getIsInitialized } from "./authProvider";
import { getSupabaseClient } from "./supabase";

const getBaseDataProvider = () =>
  supabaseDataProvider({
    instanceUrl: import.meta.env.VITE_SUPABASE_URL,
    apiKey: import.meta.env.VITE_SB_PUBLISHABLE_KEY,
    supabaseClient: getSupabaseClient(),
    sortOrder: "asc,desc.nullslast" as any,
  });

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
    async updateConfiguration(
      config: ConfigurationContextValue,
    ): Promise<ConfigurationContextValue> {
      try {
        const { data } = await baseDataProvider.update("configuration", {
          id: 1,
          data: { config },
          previousData: { id: 1 },
        });
        return data.config as ConfigurationContextValue;
      } catch (error) {
        console.warn("Failed to update configuration table, using local configuration:", error);
        return config;
      }
    },

    // VFIC custom methods — contracts verified against the live n8n workflow
    // (wridAhFQuct6IGoX) and the vfic_take_over / vfic_release RPCs.
    // The webhook 409s with conversation_not_owned unless mode='human' and
    // assigned_recruiter_id == recruiter_id.
    async sendHumanReply(zaloChatId: string, message: string) {
      const session = await getSupabaseClient().auth.getSession();
      const recruiterId = session.data.session?.user?.id;
      if (!recruiterId) throw new Error("Not authenticated");

      const response = await fetch(
        "https://bot.tingting.vip/webhook/vfic-human-reply",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            zalo_chat_id: zaloChatId,
            message,
            recruiter_id: recruiterId,
          }),
        },
      );
      if (!response.ok) {
        if (response.status === 409) {
          throw new Error("Conversation not owned — take over before replying.");
        }
        throw new Error(`Failed to send reply (${response.status})`);
      }
      return response.json();
    },

    async takeOverConversation(zaloChatId: string) {
      const session = await getSupabaseClient().auth.getSession();
      const recruiterId = session.data.session?.user?.id;
      if (!recruiterId) throw new Error("Not authenticated");

      const { data, error } = await getSupabaseClient().rpc("vfic_take_over", {
        p_zalo_chat_id: zaloChatId,
        p_recruiter: recruiterId
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
        p_recruiter: recruiterId
      });
      if (error) throw new Error(error.message);
      return data;
    },

    async createProfile(body: any) {
      const { data, error } = await getSupabaseClient().functions.invoke("vfic_create_user", {
        method: "POST",
        body
      });
      if (!data || error) {
        throw new Error(error?.message || "Failed to create user");
      }
      return data;
    },
    async signUp(body: {
      email: string;
      password: string;
      first_name: string;
      last_name: string;
    }) {
      const { data, error } = await getSupabaseClient().auth.signUp({
        email: body.email,
        password: body.password,
        options: {
          data: {
            first_name: body.first_name,
            last_name: body.last_name,
          },
        },
      });
      if (error) throw new Error(error.message);
      return data;
    },
    async salesUpdate(id: Identifier, data: Partial<any>) {
      const { data: previousData } = await baseDataProvider.getOne("sales", { id });
      if (!previousData) throw new Error("User not found");
      const { data: updated } = await baseDataProvider.update("sales", {
        id,
        data,
        previousData,
      });
      return updated;
    },
  } satisfies DataProvider;
};

export type CrmDataProvider = ReturnType<typeof getDataProviderWithCustomMethods>;

const lifeCycleCallbacks: ResourceCallbacks[] = [
  {
    resource: "leads",
    beforeGetList: async (params) => {
      return applyFullTextSearch([
        "name",
        "phone",
        "desired_job",
        "zalo_id",
      ])(params);
    },
  },
  {
    resource: "conversations",
    beforeGetList: async (params) => {
      return applyFullTextSearch(["zalo_chat_id", "assigned_recruiter_id"])(params);
    },
  },
  {
    resource: "profiles",
    beforeGetList: async (params) => {
      return applyFullTextSearch(["full_name", "email"])(params);
    },
  }
];

export const getDataProvider = () => {
  if (import.meta.env.VITE_SUPABASE_URL === undefined) {
    throw new Error("Please set the VITE_SUPABASE_URL environment variable");
  }
  if (import.meta.env.VITE_SB_PUBLISHABLE_KEY === undefined) {
    throw new Error(
      "Please set the VITE_SB_PUBLISHABLE_KEY environment variable",
    );
  }
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
