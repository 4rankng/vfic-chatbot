import { lazy, Suspense } from "react";
import type { ComponentType } from "react";
import { useLocation } from "react-router";

import { LoginSkeleton } from "./LoginSkeleton";
import { LoginPage } from "./LoginPage";

// Code-split so the forgot-password flow stays out of the initial bundle; it's
// only reached when an unauthenticated visitor navigates to /forgot-password.
const ForgotPasswordPage = lazy(async () => {
  const mod = await import("./ForgotPasswordPage");
  return { default: mod.ForgotPasswordPage as ComponentType };
});

export const StartPage = () => {
  const location = useLocation();

  if (location.pathname === "/forgot-password")
    return (
      <Suspense fallback={<LoginSkeleton />}>
        <ForgotPasswordPage />
      </Suspense>
    );
  return <LoginPage />;
};
