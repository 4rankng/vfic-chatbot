const GOOGLE_SHEET_HOSTS = new Set([
  "docs.google.com",
  "sheets.googleapis.com",
  "googleusercontent.com",
]);

export const isValidGoogleSheetUrl = (url: string): boolean => {
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return false;
  }
  if (parsed.protocol !== "https:") return false;
  const host = parsed.hostname.toLowerCase();
  if (!host || /^\d+(\.\d+){3}$/.test(host) || host.includes(":")) return false;
  return (
    GOOGLE_SHEET_HOSTS.has(host) ||
    [...GOOGLE_SHEET_HOSTS].some((allowed) => host.endsWith(`.${allowed}`))
  );
};

export type GoogleSheetGidResolution =
  | Readonly<{ ok: true; gid: number; source: "query" | "fragment" }>
  | Readonly<{
      ok: false;
      reason: "missing" | "invalid" | "conflict";
      message: string;
    }>;

const valuesFor = (raw: string): string[] =>
  new URLSearchParams(raw.trim().replace(/^#/, ""))
    .getAll("gid")
    .map((value) => value.trim());

export const resolveGoogleSheetGid = (
  url: string,
): GoogleSheetGidResolution => {
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return { ok: false, reason: "invalid", message: "Link không hợp lệ." };
  }

  const fragmentValues = valuesFor(parsed.hash);
  const source = fragmentValues.length > 0 ? "fragment" : "query";
  const selected =
    source === "fragment" ? fragmentValues : valuesFor(parsed.search);
  const unique = [...new Set(selected)];
  if (unique.length > 1) {
    return {
      ok: false,
      reason: "conflict",
      message: "Link có nhiều giá trị gid khác nhau. Hãy giữ lại đúng một gid.",
    };
  }
  const value = unique[0];
  if (!value) {
    return {
      ok: false,
      reason: "missing",
      message:
        "Link phải có gid rõ ràng trong `?gid=` hoặc `#gid=` để chọn đúng trang tính.",
    };
  }
  if (!/^\d+$/.test(value)) {
    return {
      ok: false,
      reason: "invalid",
      message:
        "gid phải là số nguyên không âm và nằm trong phạm vi an toàn của JavaScript.",
    };
  }
  try {
    const parsedValue = BigInt(value);
    if (parsedValue > BigInt(Number.MAX_SAFE_INTEGER))
      throw new Error("unsafe");
    return { ok: true, gid: Number(value), source };
  } catch {
    return {
      ok: false,
      reason: "invalid",
      message:
        "gid phải là số nguyên không âm và nằm trong phạm vi an toàn của JavaScript.",
    };
  }
};
