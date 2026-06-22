import type { AuthProvider } from "ra-core";
import { supabaseAuthProvider } from "ra-supabase-core";

import { canAccess } from "../commons/canAccess";
import { getSupabaseClient } from "./supabase";

const getBaseAuthProvider = () =>
  supabaseAuthProvider(getSupabaseClient(), {
    getIdentity: async () => {
      const profile = await getProfile();

      if (profile == null) {
        throw new Error();
      }

      return {
        id: profile.id,
        fullName: profile.full_name,
        role: profile.role,
        avatar: "", // Profiles don't have avatars yet
      };
    },
  });

// To speed up checks, we cache the initialization state
// and the current sale in the local storage. They are cleared on logout.
const IS_INITIALIZED_CACHE_KEY = "RaStore.auth.is_initialized";
const CURRENT_PROFILE_CACHE_KEY = "RaStore.auth.current_profile";

function getLocalStorage(): Storage | null {
  if (typeof window !== "undefined" && window.localStorage) {
    return window.localStorage;
  }
  return null;
}

export async function getIsInitialized() {
  // Always true for VFIC, we assume admin is seeded.
  return true;
}

const getProfile = async () => {
  const storage = getLocalStorage();
  const cachedValue = storage?.getItem(CURRENT_PROFILE_CACHE_KEY);
  if (cachedValue != null) {
    return JSON.parse(cachedValue);
  }

  const { data: dataSession, error: errorSession } =
    await getSupabaseClient().auth.getSession();

  // Shouldn't happen after login but just in case
  if (dataSession?.session?.user == null || errorSession) {
    return undefined;
  }

  const { data: dataProfile, error: errorProfile } = await getSupabaseClient()
    .from("profiles")
    .select("id, full_name, role")
    .match({ id: dataSession?.session?.user.id })
    .single();

  if (dataProfile == null || errorProfile) {
    return undefined;
  }

  storage?.setItem(CURRENT_PROFILE_CACHE_KEY, JSON.stringify(dataProfile));
  return dataProfile;
};

function clearCache() {
  const storage = getLocalStorage();
  storage?.removeItem(IS_INITIALIZED_CACHE_KEY);
  storage?.removeItem(CURRENT_PROFILE_CACHE_KEY);
}

export const getAuthProvider = (): AuthProvider => {
  const baseAuthProvider = getBaseAuthProvider();
  return {
    ...baseAuthProvider,
    login: async (params) => {
      if (params.ssoDomain) {
        const { error } = await getSupabaseClient().auth.signInWithSSO({
          domain: params.ssoDomain,
        });
        if (error) {
          throw error;
        }
        return;
      }
      return baseAuthProvider.login(params);
    },
    logout: async (params) => {
      clearCache();
      return baseAuthProvider.logout(params);
    },
    checkAuth: async (params) => {
      // Onboarding routes (sign-up / set-password / forgot-password) were
      // removed, and the init gate is always true for VFIC (the admin is
      // seeded out-of-band). Auth is fully delegated to the base Supabase
      // auth provider.
      return baseAuthProvider.checkAuth(params);
    },
    canAccess: async (params) => {
      const isInitialized = await getIsInitialized();
      if (!isInitialized) return false;

      // Get the current user
      const profile = await getProfile();
      if (profile == null) return false;

      // Compute access rights from the profile role (passed through unchanged
      // so recruiter/admin are distinguished correctly).
      const role = profile.role;
      return canAccess(role, params);
    },
    getAuthorizationDetails(authorizationId: string) {
      return getSupabaseClient().auth.oauth.getAuthorizationDetails(
        authorizationId,
      );
    },
    approveAuthorization(authorizationId: string) {
      return getSupabaseClient().auth.oauth.approveAuthorization(
        authorizationId,
      );
    },
    denyAuthorization(authorizationId: string) {
      return getSupabaseClient().auth.oauth.denyAuthorization(authorizationId);
    },
  };
};
