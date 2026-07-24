import type { Lead } from "../../types";

export type CandidateProfileUpdate = {
  name: string | null;
  phone: string | null;
  birth_year: number | null;
  age: number | null;
  living_area: string | null;
  address: string | null;
  gender: string | null;
  region: string | null;
  desired_job: string | null;
  years_experience: string | null;
  expected_salary: string | null;
  notes: string | null;
};

export type CandidateProfileDraft = {
  [Key in keyof CandidateProfileUpdate]: string;
};

export const candidateProfileFields: Array<{
  key: Exclude<keyof CandidateProfileUpdate, "notes">;
  label: string;
  inputMode?: "numeric" | "tel";
  min?: number;
  max?: number;
}> = [
  { key: "name", label: "Họ tên" },
  { key: "phone", label: "Số điện thoại", inputMode: "tel" },
  {
    key: "birth_year",
    label: "Năm sinh",
    inputMode: "numeric",
    min: 1900,
    max: new Date().getFullYear(),
  },
  { key: "age", label: "Tuổi", inputMode: "numeric", min: 15, max: 80 },
  { key: "gender", label: "Giới tính" },
  { key: "region", label: "Khu vực muốn làm" },
  { key: "living_area", label: "Khu vực đang sống" },
  { key: "address", label: "Địa chỉ hiện tại" },
  { key: "desired_job", label: "Công việc mong muốn" },
  { key: "years_experience", label: "Kinh nghiệm" },
  { key: "expected_salary", label: "Mức lương mong muốn" },
];

const nullableText = (value: unknown): string | null => {
  const text = String(value ?? "").trim();
  return text || null;
};

const nullableInteger = (value: string): number | null => {
  const text = value.trim();
  return text ? Number(text) : null;
};

export const candidateProfileDraft = (lead: Lead): CandidateProfileDraft => ({
  name: String(lead.name ?? ""),
  phone: String(lead.phone ?? ""),
  birth_year: lead.birth_year == null ? "" : String(lead.birth_year),
  age: lead.age == null ? "" : String(lead.age),
  living_area: String(lead.living_area ?? ""),
  address: String(lead.address ?? ""),
  gender: String(lead.gender ?? ""),
  region: String(lead.region ?? ""),
  desired_job: String(lead.desired_job ?? ""),
  years_experience: String(lead.years_experience ?? ""),
  expected_salary: String(lead.expected_salary ?? ""),
  notes: String(lead.notes ?? ""),
});

const candidateProfileValues = (
  draft: CandidateProfileDraft,
): CandidateProfileUpdate => ({
  name: nullableText(draft.name),
  phone: nullableText(draft.phone),
  birth_year: nullableInteger(draft.birth_year),
  age: nullableInteger(draft.age),
  living_area: nullableText(draft.living_area),
  address: nullableText(draft.address),
  gender: nullableText(draft.gender),
  region: nullableText(draft.region),
  desired_job: nullableText(draft.desired_job),
  years_experience: nullableText(draft.years_experience),
  expected_salary: nullableText(draft.expected_salary),
  notes: nullableText(draft.notes),
});

export const changedCandidateProfileValues = (
  initial: CandidateProfileDraft,
  draft: CandidateProfileDraft,
): Partial<CandidateProfileUpdate> => {
  const current = candidateProfileValues(initial);
  const next = candidateProfileValues(draft);
  return Object.fromEntries(
    (Object.keys(next) as Array<keyof CandidateProfileUpdate>)
      .filter((key) => current[key] !== next[key])
      .map((key) => [key, next[key]]),
  ) as Partial<CandidateProfileUpdate>;
};
