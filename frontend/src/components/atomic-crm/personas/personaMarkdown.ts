import type { PersonaFollowupRules } from "../types";

export const PERSONA_SECTIONS = [
  {
    title: "1. Vai trò của tôi",
    hint: "Mô tả agent là ai, phục vụ mục đích gì, và nên tạo cảm giác như thế nào.",
    aliases: ["Vai trò của tôi là gì?", "1. Vai trò của tôi (What's my job?)"],
  },
  {
    title: "2. Ai sẽ cần sự hỗ trợ của tôi?",
    hint: "Mô tả nhóm người dùng chính, bối cảnh, nhu cầu và mức độ quen công nghệ.",
    aliases: [
      "Ai cần tôi giúp?",
      "2. Ai sẽ cần sự hỗ trợ của tôi? (Who will need my help?)",
    ],
  },
  {
    title: "3. Tôi thực hiện công việc như thế nào?",
    hint: "Mô tả quy trình tư vấn, cách hỏi từng câu, nguyên tắc dùng công cụ và xử lý dữ liệu.",
    aliases: [
      "Tôi hoàn thành công việc thế nào?",
      "3. Tôi thực hiện công việc như thế nào? (How do I get things done?)",
    ],
  },
  {
    title: "4. Tôi nên tránh điều gì?",
    hint: "Liệt kê các giới hạn: không bịa dữ liệu, không lạc đề, không lộ thông tin, không dùng định dạng cấm.",
    aliases: [
      "Tôi nên tránh điều gì?",
      "4. Tôi nên tránh điều gì? (What should I avoid?)",
    ],
  },
  {
    title: "5. Bạn muốn tôi theo dõi kết quả nào?",
    hint: "Mô tả các kết quả cần thúc đẩy: lưu liên hệ, nắm nguyện vọng, đề xuất phù hợp, ứng tuyển.",
    aliases: [
      "Kết quả nào cần theo dõi?",
      "5. Bạn muốn tôi theo dõi kết quả nào? (What results do you want me to track?)",
    ],
  },
  {
    title: "6. Tôi nên giao tiếp với mọi người như thế nào?",
    hint: "Mô tả ngôn ngữ, xưng hô, thái độ, độ dài, emoji và mẫu định dạng đầu ra.",
    aliases: [
      "Tôi nên giao tiếp thế nào?",
      "6. Tôi nên giao tiếp với mọi người như thế nào? (How should I talk to people?)",
    ],
  },
  {
    title: "7. Lưu ý thêm",
    hint: "Ghi các quy tắc bổ sung, edge cases, ngày giờ hệ thống, lịch trình hoặc nhắc giới hạn hỗ trợ.",
    aliases: ["Mẹo bổ sung?", "7. Lưu ý thêm (Any extra tips?)"],
  },
] as const;

export type PersonaSectionValues = string[];

export const PERSONA_TEMPLATE = PERSONA_SECTIONS.map(
  (section) => `### ${section.title}\n(${section.hint})`,
).join("\n\n");

export const defaultPersonaFollowupRules = (): PersonaFollowupRules => ({
  hot: {
    enabled: true,
    cadence_hours: [10, 22, 46],
    eligible_stages: ["NEW"],
  },
  warm: {
    enabled: true,
    cadence_hours: [22, 46],
    eligible_stages: ["NEW"],
  },
  not_interested: {
    enabled: true,
    cadence_hours: [46],
    eligible_stages: ["NEW"],
  },
});

const emptyPersonaSections = (): PersonaSectionValues =>
  PERSONA_SECTIONS.map(() => "");

const normalizeSectionTitle = (value: string) =>
  value.trim().toLowerCase().replace(/\s+/g, " ");

const stripTemplateHint = (value: string, hint: string) => {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith("(") && trimmed.endsWith(")")) ||
    (trimmed.startsWith("[") && trimmed.endsWith("]"))
  ) {
    return "";
  }
  return trimmed === `(${hint})` || trimmed === hint ? "" : trimmed;
};

export const parsePersonaMarkdown = (markdown: string) => {
  const sections = emptyPersonaSections();
  let extraMarkdown = "";
  const matches = [...markdown.matchAll(/^###\s+(.+?)\s*$/gm)];

  if (matches.length === 0) {
    return {
      sections,
      extraMarkdown: markdown.trim(),
    };
  }

  const leading = markdown.slice(0, matches[0].index).trim();
  if (leading) extraMarkdown = leading;

  matches.forEach((match, index) => {
    const title = match[1] ?? "";
    const start = (match.index ?? 0) + match[0].length;
    const end =
      index + 1 < matches.length
        ? (matches[index + 1].index ?? markdown.length)
        : markdown.length;
    const content = markdown.slice(start, end).trim();
    const normalizedTitle = normalizeSectionTitle(title);
    const sectionIndex = PERSONA_SECTIONS.findIndex((section) =>
      [section.title, ...section.aliases].some(
        (candidate) => normalizeSectionTitle(candidate) === normalizedTitle,
      ),
    );

    if (sectionIndex >= 0) {
      sections[sectionIndex] = stripTemplateHint(
        content,
        PERSONA_SECTIONS[sectionIndex].hint,
      );
      return;
    }

    const block = `### ${title}\n${content}`.trim();
    extraMarkdown = [extraMarkdown, block].filter(Boolean).join("\n\n");
  });

  return { sections, extraMarkdown };
};

export const composePersonaMarkdown = (
  sections: PersonaSectionValues,
  extraMarkdown = "",
) =>
  [
    ...PERSONA_SECTIONS.map(
      (section, index) =>
        `### ${section.title}\n\n${(sections[index] ?? "").trim()}`,
    ),
    extraMarkdown.trim(),
  ]
    .filter(Boolean)
    .join("\n\n");

export const getCompletedPersonaSectionCount = (markdown: string) =>
  parsePersonaMarkdown(markdown).sections.filter((section) => section.trim())
    .length;

export const getPersonaAuthoredContentLength = (markdown: string) => {
  const parsed = parsePersonaMarkdown(markdown);
  return [...parsed.sections, parsed.extraMarkdown].join("\n").trim().length;
};

export const getPersonaSectionSummaries = (markdown: string) => {
  const parsed = parsePersonaMarkdown(markdown);
  return PERSONA_SECTIONS.map((section, index) => ({
    title: section.title.replace(/^\d+\.\s*/, ""),
    content: parsed.sections[index]?.trim() ?? "",
  }));
};
