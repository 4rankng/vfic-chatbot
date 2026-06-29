export const normalizeVietnameseSearchText = (value: unknown): string =>
  String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[đĐ]/g, "d")
    .toLowerCase()
    .trim();

export const vietnameseSearchIncludes = (
  haystack: unknown,
  needle: unknown,
): boolean => {
  const normalizedNeedle = normalizeVietnameseSearchText(needle);
  if (!normalizedNeedle) return true;
  return normalizeVietnameseSearchText(haystack).includes(normalizedNeedle);
};

export const vietnameseSearchKey = (...values: unknown[]): string =>
  normalizeVietnameseSearchText(values.filter(Boolean).join(" "));

export const slugifyVietnamese = (value: unknown): string =>
  normalizeVietnameseSearchText(value)
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
