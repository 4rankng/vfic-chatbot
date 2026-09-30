import type { ReactNode } from "react";
import { ShieldCheck } from "lucide-react";

import { BadgeWithIcon } from "@/components/base/badges/badges";

type AuthShellProps = {
  children: ReactNode;
  productName: string;
};

/**
 * Shared light-only authentication canvas with a responsive recruiting visual.
 *
 * The two identity chips are Untitled UI badges (`BadgeWithIcon`). `uu-scope`
 * rides each badge because the library and this console both define
 * `bg-primary` / `bg-secondary` / `text-primary` / `border-primary`; outside it
 * the chip would paint with the console's meaning. See
 * `src/styles/untitledui-theme.css`.
 *
 * The canvas itself — the `tt-hero` shell, the split brand hero with the
 * recruiting artwork, the Fraunces display face on the recovery heading, the
 * `tt-card` framing and every Vietnamese string — is deliberate brand identity
 * and is kept as it was.
 */
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
          <BadgeWithIcon
            type="pill-color"
            size="md"
            color="brand"
            className="uu-scope"
            iconLeading={ShieldCheck}
          >
            Tuyển dụng thông minh
          </BadgeWithIcon>
        </div>
        <div className="absolute left-10 top-10 hidden max-w-sm lg:block xl:left-14 xl:top-14">
          <BadgeWithIcon
            type="pill-color"
            size="md"
            color="brand"
            className="uu-scope"
            iconLeading={ShieldCheck}
          >
            Tuyển dụng thông minh
          </BadgeWithIcon>
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
        <div className="w-full max-w-sm">
          <div className="mb-6 px-1">
            <img
              src="/brand/tinghire-logo.png"
              alt="TingHire"
              className="h-auto w-[clamp(13rem,58vw,15.5rem)] max-w-full"
            />
            {productName !== "TingHire" ? (
              <span className="mt-2 block truncate text-body-sm text-muted-foreground">
                {productName}
              </span>
            ) : null}
          </div>
          {children}
        </div>
      </div>
    </section>
  </main>
);
