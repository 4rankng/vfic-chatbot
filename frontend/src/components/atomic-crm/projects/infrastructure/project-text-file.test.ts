import { describe, expect, it } from "vitest";
import {
  assertProjectTextFile,
  readProjectBriefPreview,
} from "./project-text-file";

describe("project text file preview", () => {
  it("strictly previews UTF-8 and BOM UTF-16 while keeping the original bytes", async () => {
    const source = "Tên dự án: Hà Nội\nLương 10 triệu";
    const utf8 = new File([source], "brief.csv", { type: "text/csv" });
    expect(await readProjectBriefPreview(utf8)).toBe(source);
    expect(
      await readProjectBriefPreview(
        new File([new Uint8Array([0xef, 0xbb, 0xbf]), source], "brief.txt", {
          type: "text/plain; charset=windows-1258",
        }),
      ),
    ).toBe(source);
    const utf16 = new Uint8Array(2 + source.length * 2);
    utf16.set([0xff, 0xfe]);
    [...source].forEach((char, index) => {
      utf16[2 + index * 2] = char.charCodeAt(0) & 0xff;
      utf16[3 + index * 2] = char.charCodeAt(0) >> 8;
    });
    const file = new File([utf16], "brief.txt", { type: "text/plain" });
    expect(await readProjectBriefPreview(file)).toBe(source);
    expect(new Uint8Array(await file.arrayBuffer())).toEqual(utf16);
  });

  it("skips an unsupported or corrupt browser preview for backend processing", async () => {
    const invalid = new File([new Uint8Array([0xff, 0x61])], "brief.txt");
    expect(await readProjectBriefPreview(invalid)).toBeNull();
    const utf32 = new File(
      [new Uint8Array([0xff, 0xfe, 0, 0, 65, 0, 0, 0])],
      "brief.txt",
    );
    expect(await readProjectBriefPreview(utf32)).toBeNull();
    expect(
      await readProjectBriefPreview(new File(["Lương\u0001"], "corrupt.txt")),
    ).toBeNull();
  });

  it("limits browser preview separately from the backend source ceiling", async () => {
    const source = new File(["x".repeat(3 * 1024 * 1024)], "large.log");
    expect(await readProjectBriefPreview(source)).toBeNull();
    expect(() => assertProjectTextFile(source)).not.toThrow();
    expect(() =>
      assertProjectTextFile(
        new File(["x".repeat(20 * 1024 * 1024 + 1)], "too-large.txt"),
      ),
    ).toThrow("20 MB");
  });

  it("refuses empty, binary, and YAML picks before starting training", () => {
    expect(() => assertProjectTextFile(new File([], "empty.txt"))).toThrow(
      "chưa có nội dung",
    );
    expect(() => assertProjectTextFile(new File(["x"], "office.docx"))).toThrow(
      "tệp văn bản",
    );
    expect(() => assertProjectTextFile(new File(["x"], "legacy.yaml"))).toThrow(
      "tệp văn bản",
    );
  });
});
