import { describe, expect, it } from "vitest";

import {
  CATEGORY_MARKDOWN_SCHEMAS,
  serializeCategoryMarkdown,
  type CategoryPayload,
} from "./project-knowledge-markdown";
import { parseCategoryMarkdownView } from "./category-markdown-reader";
import { PROJECT_KNOWLEDGE_CATEGORIES } from "./project-knowledge-policy";

const jobsPayload: CategoryPayload = {
  schema_version: "1.0",
  category: "jobs",
  records: [
    {
      id: "auto-jobs-379f394",
      title: "Công nhân sản xuất điện tử",
      aliases: [],
      location: "Tầng 2, LG Electronics, KCN Trảng Duệ",
      summary: "Thao tác sản xuất linh kiện bằng mạch điện tử",
      keywords: ["điện tử", "sản xuất", "LG"],
    },
    {
      id: "auto-jobs-8ac1",
      title: "Công nhân chế biến thực phẩm",
      aliases: ["CV thực phẩm"],
      location: "Nhà máy Điện Nam Sơn",
      summary: "Chế biến thực phẩm xuất khẩu",
      keywords: ["thực phẩm"],
    },
  ],
};

describe("category markdown reader", () => {
  it("reads the serializer's document back into record views", () => {
    const document = parseCategoryMarkdownView(
      serializeCategoryMarkdown("jobs", jobsPayload),
      "jobs",
    );
    expect(document.isCategoryMarkdown).toBe(true);
    expect(document.schema_version).toBe("1.0");
    expect(document.category).toBe("jobs");
    expect(document.records.map((record) => record.id)).toEqual([
      "auto-jobs-379f394",
      "auto-jobs-8ac1",
    ]);
    expect(document.records[0].title).toBe("Công nhân sản xuất điện tử");
    const location = document.records[0].fields.find(
      (field) => field.name === "location",
    );
    expect(location).toMatchObject({
      kind: "scalar",
      display: "Tầng 2, LG Electronics, KCN Trảng Duệ",
    });
    const keywords = document.records[0].fields.find(
      (field) => field.name === "keywords",
    );
    expect(keywords).toMatchObject({
      kind: "list",
      items: ["điện tử", "sản xuất", "LG"],
    });
    expect(
      document.records[0].fields.some((field) => field.name === "aliases"),
    ).toBe(false);
    expect(document.records[0].malformed).toEqual([]);
  });

  it("round-trips every category through serialize → parse", () => {
    for (const key of PROJECT_KNOWLEDGE_CATEGORIES) {
      const schema = CATEGORY_MARKDOWN_SCHEMAS[key];
      const record: Record<string, unknown> = { id: "auto-x-1" };
      for (const field of schema.fields) {
        if (field.name === "id") continue;
        if (field.kind === "scalar") record[field.name] = "giá trị";
        if (field.kind === "list") record[field.name] = ["một", "hai"];
        if (field.kind === "table")
          record[field.name] = [
            Object.fromEntries(field.columns.map((column) => [column, "x"])),
          ];
      }
      const payload: CategoryPayload = {
        schema_version: "1.0",
        category: key,
        records: [record as CategoryPayload["records"][number]],
      };
      const document = parseCategoryMarkdownView(
        serializeCategoryMarkdown(key, payload),
        key,
      );
      expect(document.isCategoryMarkdown, key).toBe(true);
      expect(document.records, key).toHaveLength(1);
      expect(document.records[0].malformed, key).toEqual([]);
      const viewNames = document.records[0].fields.map((field) => field.name);
      const schemaNames = schema.fields
        .filter((field) => field.name !== "id")
        .map((field) => field.name);
      expect(viewNames, key).toEqual(schemaNames);
    }
  });

  it("renders a hand-written document without the v1 envelope", () => {
    const document = parseCategoryMarkdownView(
      [
        "### record: hand-1",
        "title: Việc làm tự viết",
        "summary: Toàn bộ nội dung do người dùng tự soạn.",
        "",
        "### record: hand-2",
        "question: Ca làm việc thế nào?",
        "answer: Hai ca, 8 tiếng mỗi ca.",
      ].join("\n"),
      "jobs",
    );
    expect(document.isCategoryMarkdown).toBe(false);
    expect(document.records).toHaveLength(2);
    expect(document.records[0].title).toBe("Việc làm tự viết");
    expect(
      document.records[1].fields.find((field) => field.name === "answer"),
    ).toMatchObject({ kind: "scalar", display: "Hai ca, 8 tiếng mỗi ca." });
    expect(
      document.records.every((record) => record.malformed.length === 0),
    ).toBe(true);
  });

  it("collects malformed lines instead of throwing", () => {
    const document = parseCategoryMarkdownView(
      [
        "---",
        'schema_version: "1.0"',
        "category: jobs",
        "---",
        "",
        "## jobs",
        "",
        "### record: broken-1",
        "title: Bản ghi lỗi",
        "đây là một dòng không có dấu hai chấm",
        "keywords:",
        "- vẫn đọc được",
      ].join("\n"),
      "jobs",
    );
    expect(document.isCategoryMarkdown).toBe(true);
    expect(document.records).toHaveLength(1);
    expect(document.records[0].malformed).toHaveLength(1);
    expect(document.records[0].malformed[0]).toContain("Dòng 10");
    const keywords = document.records[0].fields.find(
      (field) => field.name === "keywords",
    );
    expect(keywords).toMatchObject({ kind: "list", items: ["vẫn đọc được"] });
  });

  it("keeps an empty document empty", () => {
    const document = parseCategoryMarkdownView("", "jobs");
    expect(document.records).toEqual([]);
    expect(document.isCategoryMarkdown).toBe(false);
  });
});
