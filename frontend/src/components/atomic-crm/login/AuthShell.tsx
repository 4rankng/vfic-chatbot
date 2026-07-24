import type { ReactNode } from "react";
import { ShieldCheck } from "lucide-react";

type AuthShellProps = {
  children: ReactNode;
  productName: string;
};

/** Shared light-only authentication canvas with a responsive recruiting visual. */
export const AuthShell = ({ children, productName }: AuthShellProps) => (
  <main className="tt-hero min-h-svh bg-base-200 p-3 text-base-content sm:p-6 lg:p-8">
    <section
      data-slot="auth-frame"
      className="tt-card tt-card-border grid min-h-[calc(100svh-1.5rem)] w-full max-w-[1180px] overflow-hidden rounded-2xl border border-base-300 bg-base-100 shadow-[0_24px_70px_rgb(44_58_94_/_0.12)] sm:min-h-[calc(100svh-3rem)] lg:h-[calc(100svh-4rem)] lg:min-h-[640px] lg:max-h-[820px] lg:grid-cols-[minmax(0,1.1fr)_minmax(420px,0.78fr)]"
    >
      <figure className="relative min-h-36 overflow-hidden bg-base-200 sm:min-h-44 lg:min-h-full">
        <img
          src="/login-recruiting-console-v2.webp"
          alt=""
          aria-hidden="true"
          className="absolute inset-0 size-full object-cover object-[68%_center] lg:object-center"
        />
        <div
          className="absolute inset-0 hidden bg-linear-to-r from-base-100 via-base-100/90 to-transparent lg:block"
          aria-hidden="true"
        />
        <div className="absolute left-4 top-4 lg:hidden">
          <span className="tt-badge tt-badge-primary tt-badge-soft min-h-7 gap-1.5 px-3 font-semibold">
            <ShieldCheck className="size-3.5" aria-hidden="true" />
            Tuyển dụng thông minh
          </span>
        </div>
        <div className="absolute left-10 top-10 hidden max-w-sm lg:block xl:left-14 xl:top-14">
          <span className="tt-badge tt-badge-primary tt-badge-soft min-h-8 gap-2 px-3 font-semibold">
            <ShieldCheck className="size-4" aria-hidden="true" />
            Trung tâm tuyển dụng
          </span>
          <h2 className="mt-6 text-balance text-display font-semibold leading-tight tracking-[-0.035em] text-base-content">
            Kết nối đúng người với đúng cơ hội.
          </h2>
          <p className="mt-4 max-w-xs text-body-lg leading-7 text-muted-foreground">
            Theo dõi ứng viên, hội thoại và dự án tuyển dụng trong một không
            gian vận hành thống nhất.
          </p>
        </div>
      </figure>

      <div className="relative flex items-center justify-center bg-base-200/45 px-5 py-7 sm:px-10 sm:py-10 lg:px-8 xl:px-10">
        <div className="w-full max-w-sm" aria-label={productName}>
          <div className="mb-5 flex items-center gap-3 px-1">
            <img
              src="/brand/tinghire-icon-192.png"
              alt=""
              aria-hidden="true"
              className="size-11 rounded-xl border border-base-300 object-cover shadow-sm"
            />
            <div className="min-w-0">
              <strong className="block text-subsection font-semibold tracking-tight text-base-content">
                TingHire
              </strong>
              {productName !== "TingHire" ? (
                <span className="block truncate text-body-sm text-muted-foreground">
                  {productName}
                </span>
              ) : null}
            </div>
          </div>
          {children}
        </div>
      </div>
    </section>
  </main>
);
