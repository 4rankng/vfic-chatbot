import { describe, expect, it } from "vitest";

import { PERSONA_SECTIONS, PERSONA_TEMPLATE } from "./personaMarkdown";
import {
  MAX_PERSONA_FILE_BYTES,
  parsePersonaMarkdownFile,
  validatePersonaFileUpload,
} from "./personaMarkdownIngest";

const textFile = (
  content: string,
  name = "persona.md",
  overrides: Partial<{ type: string; size: number }> = {},
) => ({
  name,
  type: "text/markdown",
  size: content.length,
  ...overrides,
});

describe("parsePersonaMarkdownFile", () => {
  it("fills all seven sections from headings at mixed levels and forms", () => {
    const parsed = parsePersonaMarkdownFile(
      [
        "# 1. Vai trò của tôi",
        "Tư vấn ứng viên 24/7.",
        "",
        "## 2. Ai sẽ cần sự hỗ trợ của tôi?",
        "Ứng viên tìm việc qua Zalo.",
        "",
        "### 3. Tôi thực hiện công việc như thế nào?",
        "Hỏi từng câu, không hỏi dồn.",
        "",
        "**4. Tôi nên tránh điều gì:**",
        "Không bịa dữ liệu.",
        "",
        "**5. Bạn muốn tôi theo dõi kết quả nào?**",
        "Số ứng tuyển đã xác nhận.",
        "",
        "#### 6. Tôi nên giao tiếp với mọi người như thế nào:",
        "Xưng hô thân thiện, ngắn gọn.",
        "",
        "###### 7. Lưu ý thêm",
        "Giới hạn hỗ trợ giờ hành chính.",
      ].join("\n"),
    );

    expect(parsed.sections).toEqual([
      "Tư vấn ứng viên 24/7.",
      "Ứng viên tìm việc qua Zalo.",
      "Hỏi từng câu, không hỏi dồn.",
      "Không bịa dữ liệu.",
      "Số ứng tuyển đã xác nhận.",
      "Xưng hô thân thiện, ngắn gọn.",
      "Giới hạn hỗ trợ giờ hành chính.",
    ]);
    expect(parsed.unknownHeadings).toEqual([]);
    expect(parsed.emptySections).toEqual([]);
    expect(parsed.extraMarkdown).toBe("");
  });

  it("matches headings without numbering, with casing and separator variants", () => {
    const parsed = parsePersonaMarkdownFile(
      [
        "## vai trò của tôi:",
        "Nội dung vai trò.",
        "",
        "**AI SẼ CẦN SỰ HỖ TRỢ CỦA TÔI**",
        "Người dùng chính.",
        "",
        "### 3) Tôi thực hiện công việc như thế nào",
        "Quy trình tư vấn.",
      ].join("\n"),
    );

    expect(parsed.sections[0]).toBe("Nội dung vai trò.");
    expect(parsed.sections[1]).toBe("Người dùng chính.");
    expect(parsed.sections[2]).toBe("Quy trình tư vấn.");
    expect(parsed.unknownHeadings).toEqual([]);
    // The untouched four are reported empty, never invented.
    expect(parsed.emptySections).toEqual([
      "Tôi nên tránh điều gì?",
      "Bạn muốn tôi theo dõi kết quả nào?",
      "Tôi nên giao tiếp với mọi người như thế nào?",
      "Lưu ý thêm",
    ]);
  });

  it("matches the known English-parenthesis alias of a section", () => {
    const parsed = parsePersonaMarkdownFile(
      [
        "### 4. Tôi nên tránh điều gì? (What should I avoid?)",
        "Không lộ thông tin ứng viên.",
      ].join("\n"),
    );

    expect(parsed.sections[3]).toBe("Không lộ thông tin ứng viên.");
    expect(parsed.unknownHeadings).toEqual([]);
  });

  it("reports an unrecognized heading and keeps its content, not a section", () => {
    const parsed = parsePersonaMarkdownFile(
      [
        "## Vai trò của tôi",
        "Tư vấn ứng viên.",
        "",
        "## Ghi chú riêng",
        "Không chia sẻ ra ngoài.",
      ].join("\n"),
    );

    expect(parsed.sections[0]).toBe("Tư vấn ứng viên.");
    expect(parsed.unknownHeadings).toEqual(["Ghi chú riêng"]);
    expect(parsed.extraMarkdown).toContain("## Ghi chú riêng");
    expect(parsed.extraMarkdown).toContain("Không chia sẻ ra ngoài.");
    expect(parsed.emptySections).toEqual(
      PERSONA_SECTIONS.slice(1).map((section) =>
        section.title.replace(/^\d+\.\s*/, ""),
      ),
    );
  });

  it("appends a repeated section heading instead of dropping either block", () => {
    const parsed = parsePersonaMarkdownFile(
      [
        "## Tôi nên tránh điều gì?",
        "Không bịa.",
        "",
        "## Lưu ý thêm",
        "Giờ hỗ trợ.",
        "",
        "## Tôi nên tránh điều gì?",
        "Không lạc đề.",
      ].join("\n"),
    );

    expect(parsed.sections[3]).toBe("Không bịa.\n\nKhông lạc đề.");
    expect(parsed.sections[6]).toBe("Giờ hỗ trợ.");
  });

  it("leaves a re-uploaded untouched template empty instead of copying hints", () => {
    const parsed = parsePersonaMarkdownFile(PERSONA_TEMPLATE);

    expect(parsed.sections).toEqual(PERSONA_SECTIONS.map(() => ""));
    expect(parsed.emptySections).toEqual(
      PERSONA_SECTIONS.map((section) => section.title.replace(/^\d+\.\s*/, "")),
    );
  });

  it("keeps lines before the first heading as extra content", () => {
    const parsed = parsePersonaMarkdownFile(
      [
        "Bản nháp cho Agent tuyển dụng.",
        "",
        "## Vai trò của tôi",
        "Nội dung.",
      ].join("\n"),
    );

    expect(parsed.sections[0]).toBe("Nội dung.");
    expect(parsed.extraMarkdown).toBe("Bản nháp cho Agent tuyển dụng.");
    expect(parsed.unknownHeadings).toEqual([]);
  });
});

describe("validatePersonaFileUpload", () => {
  it("rejects binary documents by extension and by MIME type", () => {
    expect(validatePersonaFileUpload(textFile("x", "ho-so.pdf"))).toBe(
      "Chỉ chấp nhận tệp văn bản.",
    );
    expect(validatePersonaFileUpload(textFile("x", "anh.png"))).toBe(
      "Chỉ chấp nhận tệp văn bản.",
    );
    expect(
      validatePersonaFileUpload(textFile("x", "agent", { type: "image/png" })),
    ).toBe("Chỉ chấp nhận tệp văn bản.");
  });

  it("rejects files past the 2 MiB guard", () => {
    expect(
      validatePersonaFileUpload(
        textFile("x", "persona.md", { size: MAX_PERSONA_FILE_BYTES + 1 }),
      ),
    ).toBe("Tệp quá lớn. Hãy tải lên tệp dưới 2 MB.");
  });

  it("accepts a markdown pick", () => {
    expect(
      validatePersonaFileUpload(textFile("# Vai trò", "persona.md")),
    ).toBeNull();
  });
});
