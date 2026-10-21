import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNotify } from "ra-core";
import { ChevronRight } from "lucide-react";

import { Label } from "@/components/base/input/label";
import { Toggle } from "@/components/base/toggle/toggle";

import { zaloIntegrationGateway } from "./api";
import { integrationSettingsKeys } from "./useSettingsBundle";
import { SETTINGS_NAV_ITEMS, type SettingsItemId } from "./settingsNav";

// The same keys the sections use, so a root toggle save writes back through
// the exact resource the sub-pages read.
const { cloudfone: cloudfoneSettingsKey, emailDigest: emailDigestSettingsKey } =
  integrationSettingsKeys;

/**
 * The <768px settings root (settings-mobile consult §1): three grouped inset
 * cards on a gray-50 page — "Kênh & Tích hợp" and "Tài khoản & Bảo mật" rows
 * drill into their section sub-pages, "Hiển thị & Thông báo" carries the two
 * real notification switches inline. ≥768px never renders this; the rail
 * workspace is untouched.
 *
 * The product has no theme/language settings; the group's toggles are the two
 * notification sends that exist (candidate digest mail, daily Cloudfone
 * report). Both write through the same query keys the sections use, so the
 * sub-pages show the state the root just saved.
 *
 * Row anatomy (consult §1): 44–56px rows, 16px/500 labels, gray-500 values
 * where a real current value exists, 20px gray-400 chevrons; white 12px-radius
 * cards 24px apart over gray-50.
 */
type SettingsMobileRow =
  | { kind: "section"; itemId: SettingsItemId }
  | { kind: "profile" }
  | { kind: "toggle"; id: "email-digest" | "cloudfone-report" };

const SETTINGS_MOBILE_GROUPS: Array<{
  title: string;
  rows: SettingsMobileRow[];
}> = [
  {
    title: "Kênh & Tích hợp",
    rows: [
      { kind: "section", itemId: "settings-zalo-channel" },
      { kind: "section", itemId: "settings-facebook-messenger" },
      { kind: "section", itemId: "settings-cloudfone" },
      { kind: "section", itemId: "settings-email-digest" },
      { kind: "section", itemId: "settings-geocoder" },
      { kind: "section", itemId: "settings-tingting" },
    ],
  },
  {
    title: "Tài khoản & Bảo mật",
    rows: [
      { kind: "profile" },
      { kind: "section", itemId: "settings-users" },
      { kind: "section", itemId: "settings-llm-providers" },
      { kind: "section", itemId: "settings-jev" },
    ],
  },
  {
    title: "Hiển thị & Thông báo",
    rows: [
      { kind: "toggle", id: "email-digest" },
      { kind: "toggle", id: "cloudfone-report" },
    ],
  },
];

const TOGGLE_COPY = {
  "email-digest": {
    label: "Gửi email ứng viên mới",
    on: "Đã bật gửi email ứng viên mới.",
    off: "Đã tắt gửi email ứng viên mới.",
  },
  "cloudfone-report": {
    label: "Báo cáo cuộc gọi Cloudfone",
    on: "Đã bật báo cáo cuộc gọi Cloudfone.",
    off: "Đã tắt báo cáo cuộc gọi Cloudfone.",
  },
} as const;

export const SettingsMobileGroups = ({
  onItemSelect,
}: {
  onItemSelect: (itemId: SettingsItemId) => void;
}) => {
  const notify = useNotify();
  const queryClient = useQueryClient();

  const digestQuery = useQuery({
    queryKey: emailDigestSettingsKey,
    queryFn: () => zaloIntegrationGateway.loadEmailDigestSettings(),
    staleTime: 30_000,
  });
  const cloudfoneQuery = useQuery({
    queryKey: cloudfoneSettingsKey,
    queryFn: () => zaloIntegrationGateway.loadCloudfoneSettings(),
    staleTime: 30_000,
  });

  const digestSave = useMutation({
    mutationFn: (enabled: boolean) =>
      zaloIntegrationGateway.saveEmailDigestSettings({ enabled }),
    onSuccess: (data) => {
      queryClient.setQueryData(emailDigestSettingsKey, data);
      notify(
        data.enabled
          ? TOGGLE_COPY["email-digest"].on
          : TOGGLE_COPY["email-digest"].off,
        { type: "success" },
      );
    },
    onError: () => notify("Không thể lưu cấu hình.", { type: "error" }),
  });
  const cloudfoneSave = useMutation({
    mutationFn: (enabled: boolean) =>
      zaloIntegrationGateway.saveCloudfoneSettings({ enabled }),
    onSuccess: (data) => {
      queryClient.setQueryData(cloudfoneSettingsKey, data);
      notify(
        data.enabled
          ? TOGGLE_COPY["cloudfone-report"].on
          : TOGGLE_COPY["cloudfone-report"].off,
        { type: "success" },
      );
    },
    onError: () => notify("Không thể lưu cấu hình.", { type: "error" }),
  });

  return (
    <div className="settings-mobile-groups">
      {SETTINGS_MOBILE_GROUPS.map((group) => (
        <section key={group.title}>
          <h2 className="settings-mobile-group-title text-neutral-500">
            {group.title}
          </h2>
          <div className="settings-mobile-card bg-white">
            {group.rows.map((row) => {
              if (row.kind === "profile") {
                // A real navigation row (the profile is its own route, the
                // account-menu destination) — a link, not a drill-down push.
                return (
                  <a
                    key="profile"
                    href="#/profile"
                    className="settings-mobile-row"
                  >
                    <span className="settings-mobile-row-label">
                      Hồ sơ cá nhân
                    </span>
                    <ChevronRight
                      aria-hidden="true"
                      className="settings-mobile-row-chevron text-neutral-400"
                    />
                  </a>
                );
              }

              if (row.kind === "toggle") {
                const copy = TOGGLE_COPY[row.id];
                const enabled =
                  row.id === "email-digest"
                    ? (digestQuery.data?.enabled ?? false)
                    : (cloudfoneQuery.data?.enabled ?? false);
                const ready =
                  row.id === "email-digest"
                    ? Boolean(digestQuery.data) && !digestSave.isPending
                    : Boolean(cloudfoneQuery.data) && !cloudfoneSave.isPending;

                return (
                  <div key={row.id} className="settings-mobile-row">
                    <Label
                      htmlFor={`settings-mobile-toggle-${row.id}`}
                      className="settings-mobile-row-label"
                    >
                      {copy.label}
                    </Label>
                    <Toggle
                      id={`settings-mobile-toggle-${row.id}`}
                      className="uu-scope"
                      isSelected={enabled}
                      isDisabled={!ready}
                      onChange={(next) => {
                        if (row.id === "email-digest") {
                          digestSave.mutate(next);
                        } else {
                          cloudfoneSave.mutate(next);
                        }
                      }}
                    />
                  </div>
                );
              }

              const item = SETTINGS_NAV_ITEMS.find(
                (entry) => entry.itemId === row.itemId,
              );
              const value =
                row.itemId === "settings-cloudfone" && cloudfoneQuery.data
                  ? cloudfoneQuery.data.enabled
                    ? "Đã bật"
                    : "Đang tắt"
                  : row.itemId === "settings-email-digest" && digestQuery.data
                    ? digestQuery.data.enabled
                      ? "Đã bật"
                      : "Đang tắt"
                    : undefined;

              return (
                <button
                  key={row.itemId}
                  type="button"
                  // Compound row surface: same opt-out as above.
                  data-allow-tall
                  className="settings-mobile-row"
                  onClick={() => onItemSelect(row.itemId)}
                >
                  <span className="settings-mobile-row-label">
                    {item?.label ?? row.itemId}
                  </span>
                  {value ? (
                    <span className="settings-mobile-row-value text-neutral-500">
                      {value}
                    </span>
                  ) : null}
                  <ChevronRight
                    aria-hidden="true"
                    className="settings-mobile-row-chevron text-neutral-400"
                  />
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
};
