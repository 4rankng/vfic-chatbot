type Props = {
  /** The project's FAQ category is synced from a Google Sheet on a schedule. */
  autoSyncOn: boolean;
};

/** Warns that the next FAQ sync overwrites hand-written answers. */
export const FaqAutoSyncSection = ({ autoSyncOn }: Props) => {
  if (!autoSyncOn) return null;

  return (
    <p
      className="rounded-md border border-amber-300 bg-amber-50 p-3 text-body-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
      role="status"
    >
      FAQ đang được đồng bộ tự động từ Google Sheet. Các thay đổi thủ công sẽ bị
      ghi đè ở lần đồng bộ tiếp theo.
    </p>
  );
};
