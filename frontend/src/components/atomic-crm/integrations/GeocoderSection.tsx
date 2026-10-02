import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MapPin } from "lucide-react";
import { useNotify } from "ra-core";

import { Button } from "@/components/base/buttons/button";

import type { SettingsStatusState } from "./SettingsFieldStatus";
import { SettingsGroupStatus } from "./SettingsFieldStatus";
import {
  zaloIntegrationGateway,
  type GeocoderSettings,
  type GeocoderSettingsUpdate,
} from "./api";
import { SecretField } from "./SecretField";
import { SettingsGroup, SettingsSectionPanel } from "./SettingsGroup";

/** The one API key this panel owns. */
const GEOCODER_FIELD_COUNT = 1;

/** One query key for the endpoint, so a save can write back its own response. */
const geocoderSettingsKey = ["geocoder-settings"] as const;

/**
 * The Geocoder view: the Google Maps key the distance feature uses before the
 * free Nominatim fallback. Google resolves the Vietnamese landmarks OSM lacks
 * (the 2026-10-02 incident: Nominatim put "Núi Đèo" ~120 km from Hải Phòng).
 * Stored credentials never enter form state: a blank field means "keep stored".
 */
export const GeocoderSection = () => {
  const notify = useNotify();
  const queryClient = useQueryClient();
  const [apiKeyDraft, setApiKeyDraft] = useState("");

  const settingsQuery = useQuery<GeocoderSettings>({
    queryKey: geocoderSettingsKey,
    queryFn: () => zaloIntegrationGateway.loadGeocoderSettings(),
    staleTime: 30_000,
  });
  const { data: settings, isPending, isError } = settingsQuery;

  const statusState: SettingsStatusState = isPending
    ? "loading"
    : isError
      ? "error"
      : "ready";

  const saveSettings = useMutation<
    GeocoderSettings,
    Error,
    GeocoderSettingsUpdate
  >({
    mutationFn: (body) => zaloIntegrationGateway.saveGeocoderSettings(body),
    onSuccess: (data) => {
      setApiKeyDraft("");
      queryClient.setQueryData(geocoderSettingsKey, data);
      notify("Đã lưu khoá Google Maps.", { type: "success" });
    },
    onError: () => {
      notify("Không thể lưu khoá Google Maps.", { type: "error" });
    },
  });

  const trimmedApiKey = apiKeyDraft.trim();
  const dirty = Boolean(trimmedApiKey);
  const configured = settings?.google_maps_api_key?.configured ?? false;

  const submit = () => {
    if (!settings || isError || saveSettings.isPending || !dirty) return;
    saveSettings.mutate({ google_maps_api_key: trimmedApiKey });
  };

  return (
    <SettingsSectionPanel id="settings-geocoder">
      {isError ? (
        <div role="alert" className="mb-3 text-body-sm">
          <p>Chưa tải được cấu hình geocoder.</p>
          <Button
            type="button"
            color="secondary"
            size="sm"
            className="uu-scope mt-2"
            isDisabled={settingsQuery.isFetching}
            onClick={() => void settingsQuery.refetch()}
          >
            {settingsQuery.isFetching ? "Đang tải…" : "Thử lại cấu hình"}
          </Button>
        </div>
      ) : null}
      <fieldset
        className="contents"
        disabled={!settings || isError || saveSettings.isPending}
        aria-busy={saveSettings.isPending}
      >
        <legend className="sr-only">Khoá geocoder Google Maps</legend>
        <SettingsGroup
          className="settings-tingting-card"
          title="Google Maps Geocoder"
          icon={<MapPin className="size-4" aria-hidden="true" />}
          description="Khoá dùng để tính khoảng cách từ nơi ứng viên nêu đến từng dự án. Khi có khoá, Google chạy trước Nominatim (miễn phí); không có khoá, chỉ Nominatim chạy."
          meta={
            <SettingsGroupStatus
              configured={configured ? 1 : 0}
              total={GEOCODER_FIELD_COUNT}
              state={statusState}
            />
          }
          defaultOpen
        >
          <SecretField
            id="geocoder_google_maps_api_key"
            label="Google Maps API key"
            placeholder="Nhập API key"
            configured={configured}
            statusState={statusState}
            preview={settings?.google_maps_api_key?.preview ?? null}
            value={apiKeyDraft}
            onChange={setApiKeyDraft}
            notify={notify}
            hint="Để trống để giữ khoá đã lưu. Khoá được mã hoá trước khi lưu."
          />

          <div className={`settings-llm-footer${dirty ? " is-dirty" : ""}`}>
            <Button
              type="button"
              color="primary"
              className="settings-primary-action tt-btn-touch"
              onClick={submit}
              isDisabled={!dirty || saveSettings.isPending}
            >
              {saveSettings.isPending ? "Đang lưu…" : "Lưu thay đổi"}
            </Button>
            <span className="settings-llm-footer-note">
              {dirty
                ? "Có thay đổi chưa lưu."
                : "Không có khoá, hệ thống vẫn chạy với Nominatim miễn phí."}
            </span>
          </div>
        </SettingsGroup>
      </fieldset>
    </SettingsSectionPanel>
  );
};
