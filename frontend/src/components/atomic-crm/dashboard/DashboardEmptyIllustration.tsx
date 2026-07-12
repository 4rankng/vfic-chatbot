type DashboardEmptyIllustrationProps = {
  kind: "inbox" | "calendar";
};

/**
 * Decorative, token-aware illustrations for the two recruiter attention queues.
 * They deliberately use dashboard CSS custom properties so they remain
 * lightweight and visually aligned with the operations workspace.
 */
export const DashboardEmptyIllustration = ({
  kind,
}: DashboardEmptyIllustrationProps) =>
  kind === "inbox" ? <InboxClearIllustration /> : <TodayClearIllustration />;

const InboxClearIllustration = () => (
  <svg
    className="dashboard-empty-illustration"
    viewBox="0 0 160 112"
    fill="none"
    aria-hidden="true"
    focusable="false"
  >
    <path
      d="M32 82.5V35.5c0-5.5 4.5-10 10-10h54c5.5 0 10 4.5 10 10v47c0 5.5-4.5 10-10 10H42c-5.5 0-10-4.5-10-10Z"
      fill="var(--workspace-teal-soft, #e4efff)"
      stroke="var(--workspace-border, #d8dde6)"
      strokeWidth="1.5"
    />
    <path
      d="M39 40.5h60M39 77.5h31"
      stroke="var(--workspace-border, #d8dde6)"
      strokeWidth="1.5"
      strokeLinecap="round"
    />
    <rect
      x="44"
      y="49"
      width="49"
      height="20"
      rx="7"
      fill="var(--workspace-surface, #fff)"
      stroke="var(--workspace-border, #d8dde6)"
      strokeWidth="1.5"
    />
    <circle
      cx="56"
      cy="59"
      r="5"
      fill="var(--workspace-action, #1777ff)"
      opacity=".18"
    />
    <path
      d="M52.8 61.4c.8-2.4 2.1-3.6 3.9-3.6s3.1 1.2 3.9 3.6"
      stroke="var(--workspace-action, #1777ff)"
      strokeWidth="1.5"
      strokeLinecap="round"
    />
    <circle
      cx="56.7"
      cy="55.8"
      r="2.3"
      stroke="var(--workspace-action, #1777ff)"
      strokeWidth="1.5"
    />
    <path
      d="M68 56.5h16M68 61.5h10"
      stroke="var(--workspace-ink-muted, #667085)"
      strokeWidth="1.5"
      strokeLinecap="round"
    />
    <path
      d="M109 50.5h13.5c3.6 0 6.5 2.9 6.5 6.5v9c0 3.6-2.9 6.5-6.5 6.5h-8l-5.5 4v-4.9a6.5 6.5 0 0 1-6.5-6.5v-8.1c0-3.6 2.9-6.5 6.5-6.5Z"
      fill="var(--workspace-surface, #fff)"
      stroke="var(--workspace-border, #d8dde6)"
      strokeWidth="1.5"
      strokeLinejoin="round"
    />
    <path
      d="M111.5 61.5h8.5M111.5 65.5h5"
      stroke="var(--workspace-ink-muted, #667085)"
      strokeWidth="1.5"
      strokeLinecap="round"
    />
    <circle cx="112" cy="36" r="17" fill="var(--workspace-action, #1777ff)" />
    <path
      d="m104.7 36.2 4.8 4.8 9.8-10"
      stroke="#fff"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const TodayClearIllustration = () => (
  <svg
    className="dashboard-empty-illustration"
    viewBox="0 0 160 112"
    fill="none"
    aria-hidden="true"
    focusable="false"
  >
    <rect
      x="38"
      y="22"
      width="73"
      height="70"
      rx="11"
      fill="var(--workspace-teal-soft, #e4efff)"
      stroke="var(--workspace-border, #d8dde6)"
      strokeWidth="1.5"
    />
    <path
      d="M38.5 44.5h72"
      stroke="var(--workspace-border, #d8dde6)"
      strokeWidth="1.5"
    />
    <path
      d="M57 18v10M92 18v10"
      stroke="var(--workspace-action, #1777ff)"
      strokeWidth="2"
      strokeLinecap="round"
    />
    <rect
      x="51"
      y="53"
      width="9"
      height="9"
      rx="2.5"
      fill="var(--workspace-surface, #fff)"
    />
    <path
      d="m53.2 57.4 2.1 2.1 3.8-4.1"
      stroke="var(--workspace-action, #1777ff)"
      strokeWidth="1.55"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M68 57.5h27"
      stroke="var(--workspace-ink-muted, #667085)"
      strokeWidth="1.5"
      strokeLinecap="round"
    />
    <rect
      x="51"
      y="70"
      width="9"
      height="9"
      rx="2.5"
      fill="var(--workspace-surface, #fff)"
    />
    <path
      d="m53.2 74.4 2.1 2.1 3.8-4.1"
      stroke="var(--workspace-action, #1777ff)"
      strokeWidth="1.55"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M68 74.5h19"
      stroke="var(--workspace-ink-muted, #667085)"
      strokeWidth="1.5"
      strokeLinecap="round"
    />
    <circle cx="113" cy="78" r="17" fill="var(--workspace-action, #1777ff)" />
    <path
      d="m105.7 78.2 4.8 4.8 9.8-10"
      stroke="#fff"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
