/**
 * Vietnamese slug helper for the projects domain layer.
 *
 * Domain modules may not import outward (`@/lib/**` is composition-layer
 * territory — enforced by test_architecture_boundaries), so the slug rule the
 * brief importer needs lives here. Semantics match `lib/vietnameseSearch`'s
 * `slugifyVietnamese`: NFD-fold diacritics, map đ/Đ → d, lowercase, collapse
 * every non-alphanumeric run to a dash, trim leading/trailing dashes.
 */
export const slugifyVietnamese = (value: unknown): string =>
  String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[đĐ]/g, "d")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
