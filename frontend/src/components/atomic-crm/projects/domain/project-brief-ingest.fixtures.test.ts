import { describe, expect, it } from "vitest";

import { parseProjectBrief } from "./project-brief-ingest";
// The three real recruiter briefs, copied verbatim. They are the ingestion
// contract: whatever these files genuinely carry must land in the knowledge,
// and whatever they merely demonstrate (samples, instructions) must not.
import amtranMd from "./fixtures/amtran-vsip-hai-phong.md?raw";
import fourPElectronicsMd from "./fixtures/four-p-electronics.md?raw";
import samsungSdsMd from "./fixtures/samsung-sds-kho.md?raw";

describe("parseProjectBrief — the real Amtran brief (golden)", () => {
  const brief = parseProjectBrief(amtranMd);

  it("reads the project identity the sheet states", () => {
    expect(brief.name).toBe("Dự án Amtran Vsip Hải Phòng");
    expect(brief.slug).toBe("du-an-amtran-vsip-hai-phong");
    expect(brief.aliases).toEqual(["Công ty Amtran (AmTRAN Technology)"]);
    // The work address is the VSIP industrial park; the discovery card shows
    // the city alone.
    expect(brief.location).toBe("Hải Phòng");
    expect(brief.rawText).toContain("Khu công nghiệp VSIP Thủy Nguyên");
  });

  it("carries the recruitment roles the brief lists", () => {
    // Frontmatter `target_positions` is the machine-readable list.
    expect(brief.roles).toEqual([
      "Nhân viên lắp ráp linh kiện điện tử",
      "QA",
      "SMT",
      "UI",
      "Nhựa",
      "Tivi hành chính",
      "MV",
    ]);
  });

  it("lands every genuinely-carried fact in its category", () => {
    const { categories } = brief;
    // Jobs: the job title the sheet names as Chức danh.
    expect(categories.jobs).toMatch(
      /Nhân viên lắp ráp cơ khí & linh kiện điện tử/,
    );
    // Compensation: base salary and the eight monthly allowances.
    expect(categories.compensation).toMatch(/6\.300\.000/);
    expect(categories.compensation).toMatch(/700\.000/); // đời sống
    expect(categories.compensation).toMatch(/500\.000/); // xăng xe
    expect(categories.compensation).toMatch(/400\.000/); // chuyên cần
    expect(categories.compensation).toMatch(/100\.000 VNĐ \/ tháng \(cứ sau/); // con nhỏ
    expect(categories.compensation).toMatch(/1\.000\.000/); // năng suất
    expect(categories.compensation).toMatch(/Từ 200\.000 đến 1\.000\.000/); // vị trí
    expect(categories.compensation).toMatch(/mức tối đa là 1\.000\.000/); // thâm niên
    expect(categories.compensation).toMatch(/50\.000 VNĐ \/ đêm/); // ca đêm
    // Work schedules: both shifts, the lunch break, the overtime rules.
    expect(categories.work_schedules).toMatch(/08:00 – 17:00/);
    expect(categories.work_schedules).toMatch(/12:00 – 13:00/);
    expect(categories.work_schedules).toMatch(/20:00 – 05:00/);
    // The overtime rules live in the sheet's pay-rule subsection.
    expect(
      (categories.compensation ?? "") + (categories.work_schedules ?? ""),
    ).toMatch(/tối thiểu từ 1 giờ/);
    expect(
      (categories.compensation ?? "") + (categories.work_schedules ?? ""),
    ).toMatch(/30 phút/);
    // Meals and accommodation: free canteen, NO dormitory.
    expect(categories.meals).toMatch(/miễn phí/);
    expect(categories.accommodation).toMatch(/chưa có ký túc xá/);
    // Transportation: no shuttle, but the fuel allowance exists.
    expect(categories.transportation).toMatch(/không có tuyến xe đưa đón/);
    expect(categories.transportation).toMatch(/500\.000/);
    // Insurance at the base salary.
    expect(categories.insurance).toMatch(/BHXH/);
    expect(categories.insurance).toMatch(/6\.300\.000/);
    // Benefits: the smock rule.
    expect(categories.benefits).toMatch(/áo smock/);
    // Application: the process and the document list.
    expect(categories.application).toMatch(/Đăng ký ứng tuyển/);
    expect(categories.application).toMatch(/Sơ yếu lý lịch/);
    // Contacts: the named officer and phone.
    expect(categories.contacts).toMatch(/Ngọc Thảo/);
    expect(categories.contacts).toMatch(/0963019380/);
    // Requirements: age band, no diploma, no experience, tattoos accepted.
    expect(categories.requirements).toMatch(/18 tuổi đến 37 tuổi/);
    expect(categories.requirements).toMatch(/[Kk]hông yêu cầu bằng cấp/);
    expect(categories.requirements).toMatch(/hình xăm/);
  });

  it("pairs the Hỏi/Trả lời bullets into FAQ entries", () => {
    expect(brief.faqEntries.length).toBeGreaterThanOrEqual(15);
    expect(brief.faqEntries[0].question).toBe(
      "Bên công ty đang tuyển công việc gì?",
    );
    expect(brief.faqEntries[0].answer).toMatch(/nhân viên lắp ráp cơ khí/);
  });

  it("leaves nothing unrecognised and nothing fabricated", () => {
    expect(brief.unmappedSections).toEqual([]);
    // The sheet genuinely carries every category, so nothing is punted to
    // "cần nhập tay" — and nothing outside the sheet was invented to get there.
    expect(brief.missingCategories).toEqual([]);
  });

  it("selects the by-category mode for a fully-carried brief", () => {
    expect(brief.knowledgeMode).toBe("RAG");
  });
});

describe("parseProjectBrief — the real 4P Electronics brief", () => {
  const brief = parseProjectBrief(fourPElectronicsMd);

  it("reads the discovery fields the sheet genuinely states", () => {
    expect(brief.name).toBe("Dự án 4P Electronics Tràng Duệ Hải Phòng");
    expect(brief.aliases).toEqual(["4P Electronics", "Công ty 4P"]);
    expect(brief.location).toBe("Hải Phòng");
    expect(brief.roles).toContain("SMT");
    expect(brief.roles).toContain("PCBA");
    expect(brief.roles).toContain("LQC");
  });

  it("lands the salary and logistics facts in their categories", () => {
    const { categories } = brief;
    expect(categories.compensation).toMatch(/6\.200\.000/);
    expect(categories.compensation).toMatch(/400\.000/); // chuyên cần
    expect(categories.compensation).toMatch(/600\.000 – 1\.300\.000/); // đứng máy
    expect(categories.meals).toMatch(/miễn phí/);
    expect(categories.accommodation).toMatch(/không hỗ trợ ký túc xá/);
    expect(categories.transportation).toMatch(/không hỗ trợ xe đưa đón/);
    expect(categories.transportation).toMatch(/300\.000/);
    expect(categories.insurance).toMatch(/tháng thứ 2/);
    expect(categories.benefits).toMatch(/phòng sạch/);
    expect(categories.application).toMatch(/Đăng ký thông tin ứng tuyển/);
    expect(categories.contacts).toMatch(/Admin Phượng/);
  });

  it("keeps the brief's own FAQ pairs", () => {
    expect(brief.faqEntries.length).toBeGreaterThanOrEqual(10);
  });
});

describe("parseProjectBrief — the real Samsung SDS brief", () => {
  const brief = parseProjectBrief(samsungSdsMd);

  it("reads the warehouse project's own facts", () => {
    expect(brief.name).toBe("Dự án Kho Samsung SDS Đình Vũ Hải Phòng");
    expect(brief.location).toBe("Hải Phòng");
    // The warehouse runs THREE positions, none of them a sample project.
    expect(brief.roles).toEqual([
      "Công nhân chia chọn, phân loại hàng rau, củ, quả kho mát (15°C)",
      "Công nhân chia chọn, phân loại hàng rau, củ, quả kho lạnh (5°C)",
      "Công nhân xuất hàng, nhập liệu, bốc xếp, kéo hàng",
    ]);
  });

  it("never leaks another project into the knowledge", () => {
    const serialized = JSON.stringify(brief.categories);
    // The old template shipped with LG Display / Rorze sample material; these
    // bytes do not carry it, and the parser must not fabricate it either.
    expect(serialized).not.toMatch(/LG Display|Rorze/);
  });

  it("lands the warehouse facts in their categories", () => {
    const { categories } = brief;
    expect(categories.compensation).toMatch(/300\.000 VNĐ\/ca 8/);
    expect(categories.work_schedules).toMatch(/09:00 – 18:00|09h00 – 18h00/);
    expect(categories.work_schedules).toMatch(/20:00 – 04:00|20h00 – 04h00/);
    expect(categories.meals).toMatch(/miễn phí/);
    expect(categories.meals).toMatch(/30\.000/);
    expect(categories.transportation).toMatch(/Kiến An/);
    expect(categories.insurance).toMatch(/tháng thứ 3/);
    expect(categories.contacts).toMatch(/Trần Hữu Minh Thái/);
    expect(categories.contacts).toMatch(/0394765767/);
  });

  it("carries the chatbot Q&A bank as FAQ entries", () => {
    expect(brief.faqEntries.length).toBeGreaterThanOrEqual(12);
  });
});
