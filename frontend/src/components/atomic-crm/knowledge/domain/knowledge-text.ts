import type { KnowledgeUnit } from "./knowledge-contracts";

export const localizeKnowledgeText = (value: string) =>
  value
    .replace(/\r\n?/g, "\n")
    .replace(/\\r\\n|\\n|\\r/g, "\n")
    .trim();

export const areEquivalentKnowledgeTexts = (
  candidate: string | null | undefined,
  reference: string | null | undefined,
) => {
  const [candidateKey, referenceKey] = [candidate, reference].map((value) =>
    value
      ? localizeKnowledgeText(value)
          .replace(/\s+/g, " ")
          .toLocaleLowerCase("vi")
      : "",
  );
  return Boolean(candidateKey && referenceKey && candidateKey === referenceKey);
};

export const getKnowledgeUnitPreview = (
  unit: Pick<KnowledgeUnit, "content" | "questions" | "summary">,
) => {
  const firstQuestion = unit.questions?.find((question) => question.trim());
  if (firstQuestion) return localizeKnowledgeText(firstQuestion);

  if (unit.summary?.trim()) {
    return localizeKnowledgeText(unit.summary).replace(/\s+/g, " ");
  }

  const lines = localizeKnowledgeText(unit.content)
    .split("\n")
    .map((line) => line.replace(/^[-*#\s]+/, "").trim())
    .filter(Boolean);
  const readableLine =
    lines.find(
      (line) =>
        line.toLocaleLowerCase("vi") !== "câu hỏi thường gặp" &&
        !/^(id|question|answer|question_variants|required_terms|forbidden_terms|tags)\s*:/i.test(
          line,
        ),
    ) ??
    lines[0] ??
    "Đơn vị kiến thức";

  return readableLine.replace(/\s+/g, " ");
};
