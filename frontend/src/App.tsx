import { CRM } from "@/components/atomic-crm/root/CRM";
import { useInstallationContext } from "@/components/atomic-crm/installation/installation-context";
import { i18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";
import { useEffect, useState } from "react";
import type { RuntimeGenerationBundle } from "@/components/atomic-crm/capabilities/types";
import { ensureRuntimeGeneration } from "@/components/atomic-crm/root/reset-runtime-state";
import { Button } from "@/components/ui/button";

/**
 * Application entry point
 *
 * Customize Atomic CRM by passing props to the CRM component:
 *  - companySectors
 *  - darkTheme
 *  - dealCategories
 *  - dealPipelineStatuses
 *  - dealStages
 *  - lightTheme
 *  - logo
 *  - noteStatuses
 *  - taskTypes
 *  - title
 * ... as well as all the props accepted by shadcn-admin-kit's <Admin> component.
 *
 * @example
 * const App = () => (
 *    <CRM
 *       logo="./img/logo.png"
 *       title="Acme CRM"
 *    />
 * );
 */
const ReadyRecruitmentApplication = ({
  authorityGeneration,
}: {
  authorityGeneration: number;
}) => {
  const [bundle, setBundle] = useState<RuntimeGenerationBundle | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    setBundle(null);
    void ensureRuntimeGeneration(authorityGeneration)
      .then((nextBundle) => {
        if (!cancelled) setBundle(nextBundle);
      })
      .catch(() => {
        if (!cancelled) {
          setBundle(null);
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [authorityGeneration]);

  if (failed) {
    return (
      <main className="flex min-h-svh items-center justify-center bg-base-200 p-5">
        <section className="tt-card tt-card-border w-full max-w-lg rounded-xl border bg-base-100 p-6 text-center shadow-sm">
          <h1 className="text-content-title font-semibold">
            Không thể tải không gian tuyển dụng
          </h1>
          <p className="mt-2 text-body leading-6 text-muted-foreground">
            Giao diện tuyển dụng chưa tải được. Vui lòng tải lại trang để nhận
            phiên bản mới nhất.
          </p>
          <Button className="mt-5" onClick={() => window.location.reload()}>
            Tải lại trang
          </Button>
        </section>
      </main>
    );
  }
  if (!bundle) return <RecruitmentWorkspaceLoading />;
  return <CRM bundle={bundle} i18nProvider={i18nProvider} />;
};

export const RecruitmentWorkspaceLoading = () => (
  <main
    className="flex min-h-svh items-center justify-center bg-base-200 p-5"
    aria-live="polite"
  >
    <section
      className="tt-alert flex items-center gap-3 rounded-xl border bg-base-100 px-5 py-4 shadow-sm"
      role="status"
    >
      <span
        className="tt-loading tt-loading-spinner tt-loading-sm"
        aria-hidden="true"
      />
      <span>Đang chuẩn bị không gian tuyển dụng</span>
    </section>
  </main>
);

const App = () => {
  const { manifest } = useInstallationContext();

  return (
    <ReadyRecruitmentApplication
      key={manifest.authority_generation}
      authorityGeneration={manifest.authority_generation}
    />
  );
};

export default App;
