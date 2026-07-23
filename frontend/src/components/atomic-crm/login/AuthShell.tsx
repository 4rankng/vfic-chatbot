import type { ReactNode } from "react";
import { MessageSquare, ShieldCheck, Sparkles } from "lucide-react";

type AuthShellProps = {
  children: ReactNode;
  productName: string;
};

const FEATURES = [
  { icon: ShieldCheck, label: "Tự động ưu tiên ứng viên cần chú ý" },
  { icon: MessageSquare, label: "Theo dõi hội thoại theo thời gian thực" },
  { icon: Sparkles, label: "Vận hành tuyển dụng tập trung một nơi" },
] as const;

/**
 * Shared light-only authentication canvas — UntitledUI-style split hero.
 *
 * Left: indigo→navy gradient brand panel built over the project-owned recruiting
 * artwork, with a display headline + feature bullets. Right: clean form surface.
 * Brand stays indigo (#635bff), font stays Be Vietnam Pro. All depth comes from
 * the namespaced --shadow-uu-* / --radius-uu-* tokens so the rest of the
 * console's design system is untouched.
 */
export const AuthShell = ({ children, productName }: AuthShellProps) => (
  <main className="tt-hero uu-spotlight relative flex min-h-svh items-center justify-center overflow-hidden bg-base-200 p-3 text-base-content sm:p-6 lg:p-8">
    <div
      className="uu-grid-texture pointer-events-none absolute inset-0 opacity-50"
      aria-hidden="true"
    />
    <section
      data-slot="auth-frame"
      className="uu-card animate-uu-fade-up relative grid w-full max-w-[1180px] overflow-hidden rounded-uu-3xl sm:min-h-[calc(100svh-3rem)] lg:h-[calc(100svh-4rem)] lg:min-h-[640px] lg:max-h-[820px] lg:grid-cols-[minmax(0,1.08fr)_minmax(420px,0.9fr)]"
    >
      {/* Brand panel (desktop) — gradient over the recruiting artwork. */}
      <figure className="relative hidden overflow-hidden bg-[#0a2540] lg:block">
        <img
          src="/login-recruiting-console-v2.webp"
          alt=""
          aria-hidden="true"
          className="absolute inset-0 size-full object-cover object-center opacity-35"
        />
        <div className="uu-hero-gradient absolute inset-0 opacity-90" aria-hidden="true" />
        <div className="uu-spotlight absolute inset-0" aria-hidden="true" />
        <div
          className="absolute inset-0 opacity-50"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.06) 1px, transparent 1px)",
            backgroundSize: "32px 32px",
          }}
          aria-hidden="true"
        />
        <div className="relative flex h-full flex-col justify-between p-10 text-white xl:p-14">
          <span className="inline-flex w-fit items-center gap-2 rounded-full border border-white/25 bg-white/10 px-3 py-1.5 text-helper font-semibold text-white/90 backdrop-blur-sm">
            <ShieldCheck className="size-3.5" aria-hidden="true" />
            Trung tâm tuyển dụng
          </span>

          <div className="max-w-md">
            <h2 className="text-balance text-uu-display-sm font-semibold leading-[1.1] tracking-[-0.02em] text-white">
              Kết nối đúng người với đúng cơ hội.
            </h2>
            <p className="mt-4 max-w-sm text-body-lg leading-7 text-white/75">
              Theo dõi ứng viên, hội thoại và dự án tuyển dụng trong một không gian
              vận hành thống nhất.
            </p>
            <ul className="mt-8 space-y-3">
              {FEATURES.map(({ icon: Icon, label }) => (
                <li
                  key={label}
                  className="flex items-center gap-3 text-body text-white/85"
                >
                  <span className="grid size-7 shrink-0 place-items-center rounded-full bg-white/10 ring-1 ring-inset ring-white/20">
                    <Icon className="size-4" aria-hidden="true" />
                  </span>
                  {label}
                </li>
              ))}
            </ul>
          </div>

          <p className="text-helper text-white/55">
            © {new Date().getFullYear()} Ting Ting — VFIC miniCRM
          </p>
        </div>
      </figure>

      {/* Brand chip (mobile) */}
      <div className="absolute left-4 top-4 z-10 lg:hidden">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-base-300 bg-base-100/80 px-3 py-1.5 text-helper font-semibold text-base-content shadow-uu-xs backdrop-blur-sm">
          <ShieldCheck
            className="size-3.5 text-uu-brand-600"
            aria-hidden="true"
          />
          Tuyển dụng thông minh
        </span>
      </div>

      {/* Form panel */}
      <div className="relative flex items-center justify-center bg-base-100/70 px-5 py-8 backdrop-blur-sm sm:px-10 sm:py-10 lg:px-10 xl:px-14">
        <div
          className="w-full max-w-sm animate-uu-fade-in"
          aria-label={productName}
        >
          <div className="mb-7 flex items-center gap-3">
            <img
              src="/tingting-mark.webp"
              alt=""
              aria-hidden="true"
              className="size-11 rounded-xl border border-base-300 object-cover shadow-uu-sm"
            />
            <div className="min-w-0">
              <strong className="block text-subsection font-semibold tracking-tight text-base-content">
                Ting Ting
              </strong>
              {productName !== "Ting Ting" ? (
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
