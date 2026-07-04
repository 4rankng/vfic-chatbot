import { lazy, Suspense } from "react";
import type { ComponentType } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDataProvider } from "ra-core";
import { Navigate, useLocation } from "react-router-dom";

import { useConfigurationContext } from "../root/ConfigurationContext";
import type { CrmDataProvider } from "../providers/types";
import { LoginSkeleton } from "./LoginSkeleton";
import { LoginPage } from "./LoginPage";

// Code-split so the forgot-password flow stays out of the initial bundle; it's
// only reached when an unauthenticated visitor navigates to /forgot-password.
const ForgotPasswordPage = lazy(async () => {
  const mod = await import("./ForgotPasswordPage");
  return { default: mod.ForgotPasswordPage as ComponentType };
});

export const StartPage = () => {
  const dataProvider = useDataProvider<CrmDataProvider>();
  const { disableEmailPasswordAuthentication } = useConfigurationContext();
  const location = useLocation();
  const {
    data: isInitialized,
    error,
    isPending,
  } = useQuery({
    queryKey: ["init"],
    queryFn: async () => {
      return dataProvider.isInitialized();
    },
  });

  if (location.pathname === "/forgot-password")
    return (
      <Suspense fallback={<LoginSkeleton />}>
        <ForgotPasswordPage />
      </Suspense>
    );
  if (isPending) return <LoginSkeleton />;
  if (error) return <LoginPage />;
  if (isInitialized) return <LoginPage />;
  if (disableEmailPasswordAuthentication) return <LoginPage />;

  return <Navigate to="/sign-up" />;
};
