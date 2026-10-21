import { useEffect, type ReactNode } from "react";
import { ChevronLeft } from "lucide-react";

import { useIsMobile } from "@/hooks/use-mobile";

import "../conversations/inbox.css";
import "./settings.css";
import {
  SETTINGS_NAV_ITEMS,
  SETTINGS_VIEW_COPY,
  type SettingsItemId,
  type SettingsSectionNavItem,
} from "./settingsNav";
import { SettingsMobileGroups } from "./SettingsMobileGroups";

const SettingsNavLinkContent = ({
  label,
  description,
  Icon,
}: {
  label: string;
  description: string;
  Icon: SettingsSectionNavItem["Icon"];
}) => (
  <>
    <span className="settings-side-nav-icon">
      <Icon className="size-4" />
    </span>
    <span className="settings-side-nav-copy">
      <strong>{label}</strong>
      <span>{description}</span>
    </span>
  </>
);

const SettingsSideNav = ({
  activeItemId,
  onItemSelect,
}: {
  activeItemId: SettingsItemId;
  onItemSelect: (itemId: SettingsItemId) => void;
}) => (
  <aside className="settings-side-nav" aria-label="Nhóm cài đặt">
    <div className="settings-side-nav-group">
      <span className="settings-side-nav-group-label">Mục cài đặt</span>
      <nav className="settings-side-nav-list">
        {SETTINGS_NAV_ITEMS.map((item) => {
          const active = item.itemId === activeItemId;

          return (
            <button
              key={item.label}
              type="button"
              className={`settings-side-nav-link${active ? " is-active" : ""}`}
              aria-current={active ? "page" : undefined}
              onClick={() => onItemSelect(item.itemId)}
            >
              <SettingsNavLinkContent
                label={item.label}
                description={item.description}
                Icon={item.Icon}
              />
            </button>
          );
        })}
      </nav>
    </div>
  </aside>
);

/** Desktop workspace shell; mobile renders the content bare. */
export const SettingsWorkspace = ({ children }: { children: ReactNode }) => {
  const isMobile = useIsMobile();
  if (isMobile) return <>{children}</>;

  return (
    <div className="inbox-bg-container settings-workspace">
      <div className="app settings-app" id="app">
        <section className="panel center-panel settings-center-panel">
          {children}
        </section>
      </div>
    </div>
  );
};

/**
 * Settings console chrome: the navigation rail on desktop, the drill-down
 * surfaces on mobile — the grouped inset-card root (consult §1) and one
 * sticky-back app bar per sub-page — and the slot the active section renders
 * into. Desktop keeps the rail workspace exactly as it was.
 */
export const SettingsChrome = ({
  activeItemId,
  onItemSelect,
  onMobileBack,
  mobileAtRoot,
  children,
}: {
  activeItemId: SettingsItemId;
  onItemSelect: (itemId: SettingsItemId) => void;
  /** Mobile sub-page back: one level up the drill-down. */
  onMobileBack: () => void;
  /** Mobile root (the grouped list) vs. a section sub-page. */
  mobileAtRoot: boolean;
  children: ReactNode;
}) => {
  const isMobile = useIsMobile();
  // Non-rail views (the transcripts viewer) carry their own copy; the rail
  // highlights its own entry from `activeItemId` inside SettingsSideNav.
  const headerCopy = SETTINGS_VIEW_COPY[activeItemId];

  // A new section starts at its own top; the workspace keeps one scroll box.
  useEffect(() => {
    const animationFrame = window.requestAnimationFrame(() => {
      document
        .querySelector<HTMLElement>(".settings-center-panel")
        ?.scrollTo({ top: 0, behavior: "auto" });
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [activeItemId]);

  if (isMobile && mobileAtRoot) {
    return (
      <SettingsWorkspace>
        <div className="settings-workspace-content text-foreground">
          <div className="settings-mobile-page bg-neutral-50">
            <header className="ops-command-header settings-command-header">
              <div className="ops-command-title">
                <div className="min-w-0">
                  <p className="ops-kicker">Không gian cài đặt</p>
                  <h1>Cài đặt</h1>
                  <p>Chọn khu vực bạn muốn cấu hình.</p>
                </div>
              </div>
            </header>
            <SettingsMobileGroups onItemSelect={onItemSelect} />
          </div>
        </div>
      </SettingsWorkspace>
    );
  }

  if (isMobile) {
    return (
      <SettingsWorkspace>
        <div className="settings-workspace-content text-foreground">
          <div className="settings-mobile-subpage">
            <header className="settings-mobile-appbar">
              <button
                type="button"
                className="settings-mobile-appbar-back"
                aria-label="Quay lại"
                onClick={onMobileBack}
              >
                <ChevronLeft aria-hidden="true" className="size-5" />
              </button>
              <h1 className="settings-mobile-appbar-title">
                {headerCopy.title}
              </h1>
            </header>
            <div className="settings-main">{children}</div>
          </div>
        </div>
      </SettingsWorkspace>
    );
  }

  return (
    <SettingsWorkspace>
      <div className="settings-workspace-content text-foreground">
        <div className="ops-page-shell settings-page-shell">
          <div className="settings-console">
            <SettingsSideNav
              activeItemId={activeItemId}
              onItemSelect={onItemSelect}
            />

            <div className="settings-main">
              <header className="ops-command-header settings-command-header">
                <div className="ops-command-title">
                  <div className="min-w-0">
                    <p className="ops-kicker">{headerCopy.kicker}</p>
                    <h1>{headerCopy.title}</h1>
                    <p>{headerCopy.description}</p>
                  </div>
                </div>
              </header>

              {children}
            </div>
          </div>
        </div>
      </div>
    </SettingsWorkspace>
  );
};
