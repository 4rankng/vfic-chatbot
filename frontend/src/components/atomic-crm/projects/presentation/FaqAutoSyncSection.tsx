type Props = {
  /** The project's FAQ category is synced from a Google Sheet on a schedule. */
  autoSyncOn: boolean;
};

/** Warns that the next FAQ sync overwrites hand-written answers. */
export const FaqAutoSyncSection = ({ autoSyncOn }: Props) => {
  if (!autoSyncOn) return null;

  return (
    <p
      className="rounded-md border border-warning/30 bg-warning/10 p-3 text-body-sm text-foreground"
      role="status"
    >
      FAQ đang được đồng bộ tự động từ Google Sheet. Các thay đổi thủ công sẽ bị
      ghi đè ở lần đồng bộ tiếp theo.
    </p>
  );
};
