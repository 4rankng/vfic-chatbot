import { useEffect, type ReactNode } from "react";
import { ChevronDown, Menu } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";

import "../conversations/inbox.css";
import "./settings.css";
import {
  SETTINGS_NAV_ITEMS,
  SETTINGS_VIEW_COPY,
  type SettingsItemId,
  type SettingsSectionNavItem,
} from "./settingsNav";

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

const MobileSettingsNav = ({
  activeItemId,
  onItemSelect,
}: {
  activeItemId: SettingsItemId;
  onItemSelect: (itemId: SettingsItemId) => void;
}) => {
  const activeItem =
    SETTINGS_NAV_ITEMS.find((item) => item.itemId === activeItemId) ??
    SETTINGS_NAV_ITEMS[0];

  return (
    <div className="settings-mobile-topbar">
      <Sheet>
        <SheetTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className="settings-mobile-drawer-trigger"
            aria-label="Mở danh mục cài đặt"
          >
            <Menu className="size-5" aria-hidden="true" />
            <span className="min-w-0 flex-1 text-left">
              <span className="settings-mobile-drawer-label">Cài đặt</span>
              <span className="settings-mobile-drawer-current">
                {activeItem.label}
              </span>
            </span>
            <ChevronDown className="size-4" aria-hidden="true" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="settings-mobile-drawer">
          <SheetTitle className="settings-mobile-drawer-title">
            Cài đặt
          </SheetTitle>
          <p className="settings-mobile-drawer-description">
            Chọn khu vực bạn muốn cấu hình.
          </p>
          <nav className="settings-mobile-drawer-list" aria-label="Mục cài đặt">
            {SETTINGS_NAV_ITEMS.map((item) => {
              const active = item.itemId === activeItemId;

              return (
                <SheetClose asChild key={item.itemId}>
                  <button
                    type="button"
                    className={`settings-mobile-drawer-item${active ? " is-active" : ""}`}
                    onClick={() => onItemSelect(item.itemId)}
                  >
                    <SettingsNavLinkContent
                      label={item.label}
                      description={item.description}
                      Icon={item.Icon}
                    />
                  </button>
                </SheetClose>
              );
            })}
          </nav>
        </SheetContent>
      </Sheet>
    </div>
  );
};

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
 * Settings console chrome: the navigation rail (or its mobile drawer), the view
 * header and the slot the active section renders into.
 */
export const SettingsChrome = ({
  activeItemId,
  onItemSelect,
  children,
}: {
  activeItemId: SettingsItemId;
  onItemSelect: (itemId: SettingsItemId) => void;
  children: ReactNode;
}) => {
  const isMobile = useIsMobile();
  const activeItem =
    SETTINGS_NAV_ITEMS.find((item) => item.itemId === activeItemId) ??
    SETTINGS_NAV_ITEMS[0];
  const headerCopy = SETTINGS_VIEW_COPY[activeItem.itemId];

  // A new section starts at its own top; the workspace keeps one scroll box.
  useEffect(() => {
    const animationFrame = window.requestAnimationFrame(() => {
      document
        .querySelector<HTMLElement>(".settings-center-panel")
        ?.scrollTo({ top: 0, behavior: "auto" });
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [activeItem.itemId]);

  return (
    <SettingsWorkspace>
      <div className="settings-workspace-content text-foreground">
        <div className="ops-page-shell settings-page-shell">
          <div className="settings-console">
            {isMobile ? (
              <MobileSettingsNav
                activeItemId={activeItemId}
                onItemSelect={onItemSelect}
              />
            ) : (
              <SettingsSideNav
                activeItemId={activeItemId}
                onItemSelect={onItemSelect}
              />
            )}

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
