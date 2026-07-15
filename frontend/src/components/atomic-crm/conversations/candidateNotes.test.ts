import { formatCandidateNotes } from "./candidateNotes";

describe("formatCandidateNotes", () => {
  it("keeps separately stored observations as separate list items", () => {
    const notes = [
      "Người dùng tự nhận không có trình độ, làm gì cũng được, chưa cung cấp thông tin cá nhân",
      "Người dùng tự nhận không có trình độ, sẵn sàng làm bất kỳ công việc gì Hỏi về bảo hiểm tại LG Display",
    ].join("\n");

    expect(formatCandidateNotes(notes)).toEqual([
      "Người dùng tự nhận không có trình độ, làm gì cũng được, chưa cung cấp thông tin cá nhân",
      "Người dùng tự nhận không có trình độ, sẵn sàng làm bất kỳ công việc gì Hỏi về bảo hiểm tại LG Display",
    ]);
  });

  it("removes stored bullet prefixes and exact duplicates", () => {
    expect(
      formatCandidateNotes(
        "- Có xe máy\n• Ca ngày\n1. Có xe máy\n2) Hỏi về bảo hiểm",
      ),
    ).toEqual(["Có xe máy", "Ca ngày", "Hỏi về bảo hiểm"]);
  });

  it("ignores empty note lines", () => {
    expect(formatCandidateNotes("\n - \n\t\n")).toEqual([]);
  });

  it("preserves decimal-leading facts instead of treating them as bullets", () => {
    expect(
      formatCandidateNotes("1.5 năm kinh nghiệm\n2.000.000 đồng phụ cấp"),
    ).toEqual(["1.5 năm kinh nghiệm", "2.000.000 đồng phụ cấp"]);
  });
});
