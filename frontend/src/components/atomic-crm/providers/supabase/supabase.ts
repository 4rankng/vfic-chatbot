import type { SupabaseClient } from "@supabase/supabase-js";
import { createClient } from "@supabase/supabase-js";
import { vficConfig } from "@/lib/vfic/config";

let supabaseClient: SupabaseClient | null = null;

export const getSupabaseClient = () => {
  if (!supabaseClient) {
    supabaseClient = createClient(
      vficConfig.supabaseUrl,
      vficConfig.supabasePublishableKey,
    );
  }
  return supabaseClient;
};
