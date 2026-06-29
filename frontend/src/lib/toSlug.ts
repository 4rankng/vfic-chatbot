import { slugifyVietnamese } from "./vietnameseSearch";

/**
 * Derive a stable slug value from a display label.
 * e.g. "Communication Services" → "communication-services"
 *
 * Must stay in sync with the SQL equivalent in
 * supabase/migrations/20260211194545_app_configuration.sql
 */
export const toSlug = (label: string): string =>
  slugifyVietnamese(label);
