import {
  normalizeVietnameseSearchText,
  slugifyVietnamese,
} from "@/lib/vietnameseSearch";

export const normalizeSearch = normalizeVietnameseSearchText;

export const slugifyProject = (value: string) => {
  const slug = slugifyVietnamese(value);
  return slug || `du-an-${Date.now()}`;
};
