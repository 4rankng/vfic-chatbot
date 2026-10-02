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

/** The two API keys this panel owns. */
const GEOCODER_FIELD_COUNT = 2;

/** One query key for the endpoint, so a save can write back its own response. */
const geocoderSettingsKey = ["geocoder-settings"] as const;

/**
 * The Geocoder view: the keyed geocoder credentials the distance feature tries
 * before the free Nominatim fallback. Vietmap is the primary hop and Google the
 * second (the 2026-10-02 incident: Nominatim put "Núi Đèo" ~120 km from Hải
 * Phòng, so the free provider cannot be trusted to resolve Vietnamese landmarks
 * on its own). Stored credentials never enter form state: a blank field means
 * "keep stored".
 */
export const GeocoderSection = () => {
  const notify = useNotify();
  const queryClient = useQueryClient();
  const [vietmapDraft, setVietmapDraft] = useState("");
  const [googleDraft, setGoogleDraft] = useState("");

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
      setVietmapDraft("");
      setGoogleDraft("");
      queryClient.setQueryData(geocoderSettingsKey, data);
      notify("Đã lưu khoá geocoder.", { type: "success" });
    },
    onError: () => {
      notify("Không thể lưu khoá geocoder.", { type: "error" });
    },
  });

  const trimmedVietmap = vietmapDraft.trim();
  const trimmedGoogle = googleDraft.trim();
  // A blank field means "keep stored", so only non-blank drafts are sent.
  const payload: GeocoderSettingsUpdate = {
    ...(trimmedVietmap ? { vietmap_api_key: trimmedVietmap } : {}),
    ...(trimmedGoogle ? { google_maps_api_key: trimmedGoogle } : {}),
  };
  const dirty = Boolean(trimmedVietmap || trimmedGoogle);
  const configuredCount =
    (settings?.vietmap_api_key?.configured ? 1 : 0) +
    (settings?.google_maps_api_key?.configured ? 1 : 0);

  const submit = () => {
    if (!settings || isError || saveSettings.isPending || !dirty) return;
    saveSettings.mutate(payload);
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
        <legend className="sr-only">
          Khoá geocoder Vietmap và Google Maps
        </legend>
        <SettingsGroup
          className="settings-tingting-card"
          title="Geocoder Vietmap & Google Maps"
          icon={<MapPin className="size-4" aria-hidden="true" />}
          description="Khoá dùng để tính khoảng cách từ nơi ứng viên nêu đến từng dự án. Thứ tự thử: Vietmap → Google Maps → Nominatim (miễn phí). Không có khoá nào thì chỉ Nominatim chạy."
          meta={
            <SettingsGroupStatus
              configured={configuredCount}
              total={GEOCODER_FIELD_COUNT}
              state={statusState}
            />
          }
          defaultOpen
        >
          <SecretField
            id="geocoder_vietmap_api_key"
            label="Vietmap API key"
            placeholder="Nhập API key"
            configured={settings?.vietmap_api_key?.configured ?? false}
            statusState={statusState}
            preview={settings?.vietmap_api_key?.preview ?? null}
            value={vietmapDraft}
            onChange={setVietmapDraft}
            notify={notify}
            hint="Khoá chính, dùng cho địa chỉ và địa danh Việt Nam. Để trống để giữ khoá đã lưu."
          />

          <SecretField
            id="geocoder_google_maps_api_key"
            label="Google Maps API key"
            placeholder="Nhập API key"
            configured={settings?.google_maps_api_key?.configured ?? false}
            statusState={statusState}
            preview={settings?.google_maps_api_key?.preview ?? null}
            value={googleDraft}
            onChange={setGoogleDraft}
            notify={notify}
            hint="Dùng khi Vietmap không có kết quả, cho địa chỉ ngoài Việt Nam. Để trống để giữ khoá đã lưu."
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
