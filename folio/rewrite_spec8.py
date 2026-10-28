#!/usr/bin/env python3
src = open("src/spec-8.md").read()

blocks = src.split("\n\n")
out = []
n3 = n2a = n2b = nstt = nhm = 0
for b in blocks:
    lines = b.split("\n")
    # Pattern A: Ngày + Quyết định + Đối tượng
    if (len(lines) == 3 and lines[0].startswith("- **Ngày:** ")
            and lines[1].startswith("- **Quyết định (nguyên văn/tóm tắt):** ")
            and lines[2].startswith("- **Đối tượng áp dụng:** ")):
        d = lines[0][len("- **Ngày:** "):].strip()
        q = lines[1][len("- **Quyết định (nguyên văn/tóm tắt):** "):].strip()
        o = lines[2][len("- **Đối tượng áp dụng:** "):].strip()
        out.append(f"- **{d}** — {q} (áp dụng cho {o}).")
        n3 += 1
        continue
    # Pattern B: Ngày + Đối tượng (thiếu quyết định)
    if (len(lines) == 2 and lines[0].startswith("- **Ngày:** ")
            and lines[1].startswith("- **Đối tượng áp dụng:** ")):
        d = lines[0][len("- **Ngày:** "):].strip()
        o = lines[1][len("- **Đối tượng áp dụng:** "):].strip()
        out.append(f"- **{d}** — áp dụng cho {o} (nội dung quyết định để trống trong tài liệu gốc).")
        n2a += 1
        continue
    # Pattern C: Ngày + Quyết định (thiếu đối tượng)
    if (len(lines) == 2 and lines[0].startswith("- **Ngày:** ")
            and lines[1].startswith("- **Quyết định (nguyên văn/tóm tắt):** ")):
        d = lines[0][len("- **Ngày:** "):].strip()
        q = lines[1][len("- **Quyết định (nguyên văn/tóm tắt):** "):].strip()
        out.append(f"- **{d}** — {q}.")
        n2b += 1
        continue
    # Pattern D: STT + Mô tả + Tác động
    if (len(lines) == 3 and lines[0].startswith("- **STT:** ")
            and lines[1].startswith("- **Mô tả:** ")
            and lines[2].startswith("- - **Tác động:** ")):
        n = lines[0][len("- **STT:** "):].strip()
        m = lines[1][len("- **Mô tả:** "):].strip()
        t = lines[2][len("- - **Tác động:** "):].strip()
        out.append(f"- **{n}.** {m} — tác động: {t}.")
        nstt += 1
        continue
    # Pattern E: Hạng mục + Lý do hủy
    if (len(lines) == 2 and lines[0].startswith("- **Hạng mục:** ")
            and lines[1].startswith("- **Lý do hủy / ghi chú:** ")):
        h = lines[0][len("- **Hạng mục:** "):].strip()
        l = lines[1][len("- **Lý do hủy / ghi chú:** "):].strip()
        out.append(f"- **{h}** — {l}.")
        nhm += 1
        continue
    out.append(b)

src = "\n\n".join(out)
open("after/spec-8.md", "w").write(src)
print(f"3-field: {n3}, ngày+đối tượng: {n2a}, ngày+quyết định: {n2b}, STT: {nstt}, hạng mục: {nhm}")
print("written", len(src))
