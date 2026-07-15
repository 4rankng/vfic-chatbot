import { QueryClient } from "@tanstack/react-query";
import { CircleAlert, Loader2, LogOut, Settings2 } from "lucide-react";
import {
  CustomRoutes,
  memoryStore,
  useGetIdentity,
  useLogout,
  usePermissions,
} from "ra-core";
import type { ReactNode } from "react";
import { Navigate, Route } from "react-router";

import { Admin } from "@/components/admin/admin";
import { Notification } from "@/components/admin/notification";
import { Button } from "@/components/ui/button";
import { getAuthProvider, getDataProvider } from "../providers/rest";
import { i18nProvider } from "../providers/commons/i18nProvider";
import { StartPage } from "../login/StartPage";
import { ForgotPasswordPage } from "../login/ForgotPasswordPage";
import { InstallationWizard } from "../settings/installation/InstallationWizard";
import { useInstallationContext } from "./installation-context";

const setupQueryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 0, gcTime: 0, networkMode: "online", retry: false },
    mutations: { networkMode: "online", retry: false },
  },
});
const setupStore = memoryStore();
const setupAuthProvider = getAuthProvider();
const setupDataProvider = getDataProvider();

export const SetupLayout = ({ children }: { children: ReactNode }) => {
  const logout = useLogout();
  const { data: identity } = useGetIdentity();
  const logoutSafely = async () => {
    setupQueryClient.clear();
    try {
      window.localStorage.removeItem("app.configuration");
    } catch {
      // The setup shell never reads this legacy key.
    }
    await logout();
  };

  return (
    <div className="min-h-svh bg-muted/30 text-foreground">
      <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex min-h-16 w-full max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-card">
              <Settings2 className="size-5" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <p className="truncate font-semibold">Thiết lập hệ thống</p>
              <p className="truncate text-xs text-muted-foreground">
                {identity?.fullName ?? "Tài khoản quản trị"}
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            className="min-h-11 shrink-0"
            onClick={() => void logoutSafely()}
          >
            <LogOut className="size-4" aria-hidden="true" />
            <span className="hidden sm:inline">Đăng xuất</span>
          </Button>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-8">
        {children}
      </main>
      <Notification />
    </div>
  );
};

const WaitingForAdministrator = () => (
  <section className="mx-auto max-w-xl rounded-xl border bg-card p-6 sm:p-8">
    <CircleAlert className="size-6" aria-hidden="true" />
    <h1 className="mt-4 text-xl font-semibold">Đang chờ quản trị viên thiết lập</h1>
    <p className="mt-2 text-sm leading-6 text-muted-foreground">
      Không gian làm việc sẽ mở sau khi quản trị viên hoàn tất và xác nhận cấu hình.
    </p>
  </section>
);

const RuntimeRecovery = ({ title, description }: { title: string; description: string }) => (
  <section className="mx-auto max-w-xl rounded-xl border bg-card p-6 sm:p-8" role="alert">
    <CircleAlert className="size-6" aria-hidden="true" />
    <h1 className="mt-4 text-xl font-semibold">{title}</h1>
    <p className="mt-2 text-sm leading-6 text-muted-foreground">{description}</p>
  </section>
);

const SetupRoute = () => {
  const { permissions, isPending } = usePermissions();
  const { manifest } = useInstallationContext();

  if (isPending) {
    return (
      <div className="flex min-h-48 items-center justify-center" aria-live="polite">
        <Loader2 className="size-6 animate-spin" aria-hidden="true" />
        <span className="sr-only">Đang kiểm tra quyền truy cập</span>
      </div>
    );
  }
  if (permissions !== "admin") return <WaitingForAdministrator />;

  if (manifest.lifecycle === "UPGRADE_REQUIRED") {
    return (
      <RuntimeRecovery
        title="Cần nâng cấp phiên bản"
        description="Phiên bản giao diện hiện tại không tương thích với cấu hình đã lưu. Không gian nghiệp vụ vẫn bị khóa để bảo vệ dữ liệu."
      />
    );
  }
  if (manifest.lifecycle === "ACTIVE") {
    return (
      <RuntimeRecovery
        title="Cấu hình đang hoạt động chưa sẵn sàng"
        description="Không gian nghiệp vụ tạm thời bị khóa. Vui lòng kiểm tra trạng thái máy chủ trước khi tiếp tục."
      />
    );
  }

  return <InstallationWizard />;
};

const SetupIndex = () => <Navigate to="/setup" replace />;

export const SetupApplication = () => (
  <Admin
    dataProvider={setupDataProvider}
    authProvider={setupAuthProvider}
    i18nProvider={i18nProvider}
    queryClient={setupQueryClient}
    store={setupStore}
    loginPage={StartPage}
    layout={SetupLayout}
    dashboard={SetupIndex}
    catchAll={SetupIndex}
    requireAuth
    disableTelemetry
  >
    <CustomRoutes>
      <Route path="/setup" element={<SetupRoute />} />
    </CustomRoutes>
    <CustomRoutes noLayout>
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
    </CustomRoutes>
  </Admin>
);
