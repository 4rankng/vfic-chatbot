/**
 * The call-records viewer as a workspace page (CHAT-15).
 *
 * Every signed-in user — recruiter or admin — opens the stored Cloudfone
 * transcripts from here: the sidebar's "Bản ghi cuộc gọi" destination lands
 * on this page. The Cloudfone set-up (credentials, sync, mapping) stays
 * admin-only inside the settings console, so this page deliberately carries
 * no link back into it — for a non-admin there is no config surface to
 * return to. Timestamps render on the Vietnam clock (ICT, GMT+7) inside the
 * viewer, per the vietnamTime contract.
 */
import { PageHeading, PageShell } from "../kit";
import { CloudfoneTranscriptsSection } from "./CloudfoneTranscriptsSection";
import { SETTINGS_VIEW_COPY } from "./settingsNav";

const COPY = SETTINGS_VIEW_COPY["settings-cloudfone-transcripts"];

export const CallRecordsPage = () => (
  <PageShell>
    <PageHeading
      eyebrow={COPY.kicker}
      title={COPY.title}
      subtitle={COPY.description}
    />
    <CloudfoneTranscriptsSection />
  </PageShell>
);
