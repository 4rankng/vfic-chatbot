import { describe, expect, it } from "vitest";
import { parseProjectBrief, type ProjectBrief } from "./project-brief-ingest";

it("extracts named categories from one plain-text file without Markdown headings", () => {
  const brief = parseProjectBrief(`Tên dự án: Xưởng Hải Phòng
Địa chỉ: KCN VSIP, Hải Phòng
Vị trí tuyển dụng: Công nhân
Lương: Lương cơ bản 6.000.000 đồng/tháng
Yêu cầu: Từ 18 tuổi, không cần kinh nghiệm
Lịch làm việc: Giờ hành chính
Chỗ ở: Không có ký túc xá
Bữa ăn: Có bữa trưa miễn phí
Liên hệ: Bộ phận tuyển dụng, 0901234567`);
  expect(brief.name).toBe("Xưởng Hải Phòng");
  expect(brief.location).toBe("Hải Phòng");
  expect(brief.roles).toEqual(["Công nhân"]);
  expect(brief.categories.compensation).toContain("6.000.000");
  expect(brief.categories.requirements).toContain("Từ 18 tuổi");
  expect(brief.categories.work_schedules).toContain("Giờ hành chính");
  expect(brief.categories.accommodation).toContain("Không có ký túc xá");
  expect(brief.categories.meals).toContain("Có bữa trưa miễn phí");
  expect(brief.missingCategories).toContain("insurance");
});

/** A trimmed but structurally faithful slice of the real brief: the overview
 *  table, the Q&A markers, the `<br>`-joined highlight cell, the LaTeX process
 *  arrow, and the numbered section headings. */
const BRIEF = `# CÔNG TY CỔ PHẦN CUNG ỨNG NHÂN LỰC VFIC
## PHIẾU THU THẬP THÔNG TIN DỰ ÁN TUYỂN DỤNG

## PHẦN I: THÔNG TIN TỔNG QUAN VỀ DỰ ÁN

| Hạng mục thông tin | Mô tả nội dung |
| :--- | :--- |
| **Tên dự án tuyển dụng** | 4P ELECTRONIC |
| **Tên viết tắt / Tên thường gọi** | 4P Electronics / 4P Hải Phòng |
| **Địa chỉ nơi làm việc** | Tầng 2 Công ty LGE, KCN Tràng Duệ, An Phong, TP. Hải Phòng |
| **Vị trí tuyển dụng chính** | Công nhân sản xuất điện tử (SMT, PCBA, KHO (MAT, PPS), Chất lượng QA, LQC…) |
| **Tóm tắt công việc** | Sản xuất, lắp ráp và kiểm tra linh kiện bảng mạch điện tử cho ngành ô tô. |
| **Các điểm nổi bật thu hút** | - Không yêu cầu bằng cấp; chăm chỉ, chịu khó.<br>- Thưởng thâm niên: 100.000 – 1.000.000 đồng/tháng.<br>- Đóng đầy đủ BHXH, BHYT, BHTN. |

## PHẦN II: CHI TIẾT NỘI DUNG TƯ VẤN ỨNG VIÊN

### 1. Vị trí tuyển dụng & Công việc cụ thể
* **Câu hỏi thường gặp:**
  * Bên công ty đang tuyển công việc gì?
* **Thông tin phản hồi:**
  * **Vị trí tuyển:** Công nhân sản xuất (SMT, PCBA, KHO, QA, LQC...).
  * **Mô tả công việc hàng ngày:** Thao tác lắp ráp, vận hành máy và kiểm tra sản xuất linh kiện bảng mạch điện tử cho xe ô tô.

### 3. Tiền lương, phụ cấp & Tăng ca
* **Câu hỏi thường gặp:**
  * Lương cơ bản bao nhiêu tiền?
* **Thông tin phản hồi:**
  * **Lương cơ bản:** 6.200.000 – 6.300.000 đồng/tháng.
  * **Hình thức & Chu kỳ chi trả:** Trả lương định kỳ theo tháng.

### 5. Chế độ ăn uống & Chỗ ở
* **Câu hỏi thường gặp:**
  * Cơm công ty có mất tiền không?
* **Thông tin phản hồi:**
  * **Cơm ca:** Được phục vụ hoàn toàn **MIỄN PHÍ** tại nhà ăn công ty trong ca làm việc.
  * **Chỗ ở / Ký túc xá:** Công ty **không hỗ trợ** ký túc xá (người lao động tự túc chỗ ở hoặc thuê trọ gần KCN).

### 8. Môi trường làm việc & Bảo hộ lao động
* **Câu hỏi thường gặp:**
  * Có phải mặc quần áo phòng sạch không?
* **Thông tin phản hồi:**
  * **Đồng phục:** Mặc trang phục chuyên dụng phòng sạch (áo smock).
  * **Chế độ phúc lợi bổ sung:** Được tham gia hoạt động du lịch, nghỉ mát hàng năm do công ty tổ chức.
  * **Chế độ bảo hiểm xã hội:** Tham gia đóng đầy đủ theo quy định của Luật Lao động.

### 9. Quy trình phỏng vấn & Hồ sơ nhận việc
* **Câu hỏi thường gặp:**
  * Đi phỏng vấn có khó không?
* **Thông tin phản hồi:**
  * $$\\text{Đăng ký ứng tuyển} \\longrightarrow \\text{Phỏng vấn} \\longrightarrow \\text{Khám sức khỏe} \\longrightarrow \\text{Nhận việc / Đi làm}$$

### 12. Ghi chú riêng của nhà
* **Thông tin phản hồi:**
  * Một ghi chú không thuộc danh mục nào.
`;

const parsed = (): ProjectBrief => parseProjectBrief(BRIEF);

describe("parseProjectBrief — discovery fields", () => {
  it("reads the project identity out of the overview table", () => {
    const brief = parsed();
    expect(brief.name).toBe("4P ELECTRONIC");
    expect(brief.slug).toBe("4p-electronic");
    expect(brief.aliases).toEqual(["4P Electronics", "4P Hải Phòng"]);
  });

  it("shortens the work address to the city the discovery card shows", () => {
    expect(parsed().location).toBe("Hải Phòng");
  });

  it("splits the role cell into the recruiter's own comma list", () => {
    const roles = parsed().roles;
    expect(roles[0]).toBe("Công nhân sản xuất điện tử");
    expect(roles).toContain("SMT");
    expect(roles).toContain("PCBA");
    expect(roles).toContain("KHO (MAT, PPS)");
  });

  it("keeps a square-bracket group whole inside the role cell", () => {
    // Production incident: "KHO [MAT, PPS]" was torn into the junk records
    // "KHO [MAT" and "PPS]" by a comma split that only guarded parentheses;
    // the retrieval selftest then refused the mangled "KHO [MAT" record.
    const brief = parseProjectBrief(
      [
        "## PHẦN I: THÔNG TIN TỔNG QUAN VỀ DỰ ÁN",
        "",
        "| Hạng mục thông tin | Mô tả nội dung |",
        "| :--- | :--- |",
        "| **Tên dự án tuyển dụng** | 4P ELECTRONIC |",
        "| **Địa chỉ nơi làm việc** | Hải Phòng |",
        "| **Vị trí tuyển dụng chính** | Công nhân sản xuất điện tử (SMT, PCBA, KHO [MAT, PPS], QA) |",
      ].join("\n"),
    );
    expect(brief.roles).toContain("KHO [MAT, PPS]");
    expect(brief.roles).not.toContain("KHO [MAT");
    expect(brief.roles).not.toContain("PPS]");
  });

  it("breaks a standalone square-bracket role into its own skills", () => {
    const brief = parseProjectBrief(
      "Tên dự án: 4P ELECTRONIC\nĐịa điểm: Hải Phòng\nVị trí tuyển dụng: KHO [MAT, PPS]",
    );
    expect(brief.roles).toEqual(["KHO", "MAT", "PPS"]);
  });

  it("reads the summary and splits the <br>-joined highlight cell", () => {
    const brief = parsed();
    expect(brief.summary).toBe(
      "Sản xuất, lắp ráp và kiểm tra linh kiện bảng mạch điện tử cho ngành ô tô.",
    );
    expect(brief.highlights).toHaveLength(3);
    expect(brief.highlights[1]).toMatch(/Thưởng thâm niên/);
  });

  it("ignores the table header and alignment rows", () => {
    const brief = parsed();
    expect(brief.name).not.toMatch(/Mô tả nội dung/);
    expect(brief.summary).not.toMatch(/Hạng mục/);
  });
});

describe("parseProjectBrief — knowledge categories", () => {
  it("maps each numbered heading onto its category", () => {
    const { categories } = parsed();
    expect(categories.jobs).toMatch(/Mô tả công việc hàng ngày/);
    expect(categories.compensation).toMatch(/6\.200\.000/);
  });

  it("keeps the accent-stripped emphasis out of the knowledge body", () => {
    expect(parsed().categories.meals).toMatch(
      /Được phục vụ hoàn toàn MIỄN PHÍ/,
    );
  });

  it("routes a straddling section's bullets to the right categories", () => {
    const { categories } = parsed();
    // The meal section's housing answers belong to accommodation, not meals.
    expect(categories.meals).toMatch(/nhà ăn công ty/);
    expect(categories.meals).not.toMatch(/ký túc xá/);
    expect(categories.accommodation).toMatch(/không hỗ trợ/);
    // The work-environment section's statutory schemes belong to insurance.
    expect(categories.benefits).toMatch(/áo smock/);
    expect(categories.insurance).toMatch(/Luật Lao động/);
  });

  it("renders the LaTeX process arrow as readable prose", () => {
    expect(parsed().categories.application).toMatch(
      /Đăng ký ứng tuyển → Phỏng vấn → Khám sức khỏe → Nhận việc \/ Đi làm/,
    );
  });

  it("names the categories the brief does not cover instead of inventing them", () => {
    const brief = parsed();
    expect(brief.missingCategories).toContain("transportation");
    expect(brief.categories.transportation).toBeUndefined();
  });

  it("keeps an unrecognised section visible rather than dropping it", () => {
    const brief = parsed();
    expect(brief.unmappedSections).toHaveLength(1);
    expect(brief.unmappedSections[0].title).toMatch(/Ghi chú riêng/);
    expect(brief.unmappedSections[0].body).toMatch(/không thuộc danh mục nào/);
  });

  it("pairs a section's questions with its answers", () => {
    const { faqEntries } = parsed();
    expect(faqEntries[0]).toEqual({
      question: "Bên công ty đang tuyển công việc gì?",
      answer:
        "Vị trí tuyển: Công nhân sản xuất (SMT, PCBA, KHO, QA, LQC...).\nMô tả công việc hàng ngày: Thao tác lắp ráp, vận hành máy và kiểm tra sản xuất linh kiện bảng mạch điện tử cho xe ô tô.",
    });
  });

  it("chooses the by-category mode once the brief fills several categories", () => {
    expect(parsed().knowledgeMode).toBe("RAG");
  });
});

describe("parseProjectBrief — plain label lines", () => {
  // The shape recruiters actually hand over when they are not pasting a
  // table: one label per line, value on the next line.
  const LABEL_BRIEF = `Tên dự án *
LG Display Hải Phòng

Mã dự án *
lg-display-hai-phong

Tên gọi khác
LG, LGD

Cách quản lý kiến thức
Một nội dung

## Giúp ứng viên tìm đúng dự án

Tóm tắt *
Sản xuất màn hình cho các dòng xe điện.

Địa điểm *
Hải Phòng

Vị trí tuyển dụng
Sản xuất, kiểm tra

Điểm nổi bật
Không yêu cầu kinh nghiệm
`;

  it("fills the discovery fields the form would otherwise ask for", () => {
    const brief = parseProjectBrief(LABEL_BRIEF);
    expect(brief.name).toBe("LG Display Hải Phòng");
    expect(brief.slug).toBe("lg-display-hai-phong");
    expect(brief.aliases).toEqual(["LG, LGD"]);
    expect(brief.summary).toBe("Sản xuất màn hình cho các dòng xe điện.");
    expect(brief.location).toBe("Hải Phòng");
    expect(brief.roles).toEqual(["Sản xuất", "kiểm tra"]);
    expect(brief.highlights).toEqual(["Không yêu cầu kinh nghiệm"]);
  });

  it("honors the brief's own knowledge-mode line", () => {
    expect(parseProjectBrief(LABEL_BRIEF).knowledgeMode).toBe("DIRECT_CONTEXT");
    const brief = parseProjectBrief(
      "Tên dự án *\nLG\n\nCách quản lý kiến thức\nTheo danh mục",
    );
    expect(brief.knowledgeMode).toBe("RAG");
  });

  it("prefers `Label: value` one-liners when the brief uses them", () => {
    const brief = parseProjectBrief(
      "Tên dự án: LG Display Hải Phòng\nĐịa điểm: Hải Phòng\nVị trí tuyển dụng: Sản xuất, kiểm tra",
    );
    expect(brief.name).toBe("LG Display Hải Phòng");
    expect(brief.location).toBe("Hải Phòng");
    expect(brief.roles).toEqual(["Sản xuất", "kiểm tra"]);
  });

  it("keeps the overview table canonical when both shapes appear", () => {
    const brief = parseProjectBrief(
      "| Tên dự án | 4P ELECTRONIC |\n|---|---|\n\nTên dự án *\nLG Display Hải Phòng",
    );
    expect(brief.name).toBe("4P ELECTRONIC");
  });

  it("never mistakes prose for a label", () => {
    const brief = parseProjectBrief(
      "Tên dự án phải dễ nhớ và ngắn gọn\nKhông yêu cầu kinh nghiệm",
    );
    expect(brief.name).toBe("");
    expect(brief.highlights).toEqual([]);
  });
});

describe("parseProjectBrief — degenerate input", () => {
  it("returns the empty brief for an empty file", () => {
    const brief = parseProjectBrief("   \n  ");
    expect(brief.name).toBe("");
    expect(brief.knowledgeMode).toBe("DIRECT_CONTEXT");
    expect(brief.missingCategories).toHaveLength(12);
  });

  it("keeps a prose question heading out of the FAQ bank", () => {
    // Regression: "1. Chúng ta làm gì?" ended with ?, so the section became a
    // FAQ record whose "answer" was the project description.
    const brief = parseProjectBrief(
      [
        "# Phiếu thu thập thông tin",
        "",
        "## Ngân hàng câu hỏi",
        "",
        "### ❓ Công ty tuyển vị trí gì?",
        "Tuyển công nhân lắp ráp.",
        "",
        "## Thông tin chung",
        "",
        "### 1. Chúng ta làm gì?",
        "THÔNG TIN CHUNG: Công ty Cổ phần Nhân lực Quốc tế.",
      ].join("\n"),
    );
    expect(brief.faqEntries.map((entry) => entry.question)).toEqual([
      "Công ty tuyển vị trí gì?",
    ]);
    expect(brief.faqEntries[0].answer).toBe("Tuyển công nhân lắp ráp.");
  });

  it("leaves the name empty — never a fabricated one — when the brief has none", () => {
    const brief = parseProjectBrief("## Ghi chú\n\nMột dòng.");
    expect(brief.name).toBe("");
    expect(brief.slug).toBe("");
  });
});
