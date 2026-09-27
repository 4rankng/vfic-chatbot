export type CredentialFieldNotify = (
  message: string,
  options: { type: "success" | "error" },
) => void;

export const copyCredentialFieldValue = async (
  label: string,
  value: string,
  notify: CredentialFieldNotify,
) => {
  try {
    if (!navigator.clipboard?.writeText) {
      throw new Error("Clipboard unavailable");
    }
    await navigator.clipboard.writeText(value);
    notify(`Đã sao chép ${label}.`, { type: "success" });
  } catch {
    notify(`Không thể sao chép ${label}.`, { type: "error" });
  }
};
