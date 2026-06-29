import { useQuery } from "@tanstack/react-query";
import { useDataProvider } from "ra-core";
import { Navigate, useLocation } from "react-router-dom";

import { useConfigurationContext } from "../root/ConfigurationContext";
import type { CrmDataProvider } from "../providers/types";
import { LoginSkeleton } from "./LoginSkeleton";
import { LoginPage } from "./LoginPage";
import { ForgotPasswordPage } from "./ForgotPasswordPage";

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

  if (location.pathname === "/forgot-password") return <ForgotPasswordPage />;
  if (isPending) return <LoginSkeleton />;
  if (error) return <LoginPage />;
  if (isInitialized) return <LoginPage />;
  if (disableEmailPasswordAuthentication) return <LoginPage />;

  return <Navigate to="/sign-up" />;
};
