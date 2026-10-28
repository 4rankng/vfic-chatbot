#!/usr/bin/env python3
src = open("src/spec-8.md").read()

def finish(q):
    q = q.strip()
    if q and not q.endswith((".", "”", '"', ")", "!", "?", "…")):
        q += "."
    return q

blocks = src.split("\n\n")
out = []
n3 = n2a = n2b = nstt = nhm = 0
for b in blocks:
    lines = b.split("\n")
    if (len(lines) == 3 and lines[0].startswith("- **Ngày:** ")
            and lines[1].startswith("- **Quyết định (nguyên văn/tóm tắt):** ")
            and lines[2].startswith("- **Đối tượng áp dụng:** ")):
        d = lines[0][len("- **Ngày:** "):].strip()
        q = finish(lines[1][len("- **Quyết định (nguyên văn/tóm tắt):** "):])
        o = lines[2][len("- **Đối tượng áp dụng:** "):].strip().rstrip(".") + ""
        out.append(f"- **Ngày {d}** — {q} Quyết định áp dụng cho {o}.")
        n3 += 1
        continue
    if (len(lines) == 2 and lines[0].startswith("- **Ngày:** ")
            and lines[1].startswith("- **Đối tượng áp dụng:** ")):
        d = lines[0][len("- **Ngày:** "):].strip()
        o = lines[1][len("- **Đối tượng áp dụng:** "):].strip()
        out.append(f"- **Ngày {d}** — mục này chỉ ghi phạm vi áp dụng: {o}; nội dung quyết định để trống trong tài liệu gốc.")
        n2a += 1
        continue
    if (len(lines) == 2 and lines[0].startswith("- **Ngày:** ")
            and lines[1].startswith("- **Quyết định (nguyên văn/tóm tắt):** ")):
        d = lines[0][len("- **Ngày:** "):].strip()
        q = finish(lines[1][len("- **Quyết định (nguyên văn/tóm tắt):** "):])
        out.append(f"- **Ngày {d}** — {q}")
        n2b += 1
        continue
    if (len(lines) == 3 and lines[0].startswith("- **STT:** ")
            and lines[1].startswith("- **Mô tả:** ")
            and lines[2].startswith("- - **Tác động:** ")):
        n = lines[0][len("- **STT:** "):].strip()
        m = lines[1][len("- **Mô tả:** "):].strip().rstrip(".") + ""
        t = lines[2][len("- - **Tác động:** "):].strip()
        out.append(f"- **Vấn đề {n}: {m}** — tác động của vấn đề này: {t}.")
        nstt += 1
        continue
    if (len(lines) == 2 and lines[0].startswith("- **Hạng mục:** ")
            and lines[1].startswith("- **Lý do hủy / ghi chú:** ")):
        h = lines[0][len("- **Hạng mục:** "):].strip()
        l = lines[1][len("- **Lý do hủy / ghi chú:** "):].strip()
        out.append(f"- **{h}** — lý do hủy / ghi chú: {l}.")
        nhm += 1
        continue
    out.append(b)

src = "\n\n".join(out)

# Section lead sentences (descriptive, no new facts)
LEADS = [
("### 8.1.1 Tờ khai / chứng từ / container\n\n",
 "### 8.1.1 Tờ khai / chứng từ / container\n\nCác quyết định trong nhóm này xoay quanh mô hình tờ khai theo container, thứ tự các trường nhận diện lô và hành vi thêm/bớt container; mỗi dòng ghi ngày ra quyết định, nội dung chốt và phạm vi áp dụng.\n\n"),
("### 8.1.2 Điều phối / điều vận\n\n",
 "### 8.1.2 Điều phối / điều vận\n\nNhóm này tập hợp các quyết định về màn điều phối và điều vận — từ phát lệnh, gán xe, đổi nhà xe đến bố cục bảng kế hoạch; mỗi dòng ghi ngày ra quyết định, nội dung chốt và phạm vi áp dụng.\n\n"),
("### 8.1.3 Cước phí / gộp hàng LCL / kế toán / công nợ\n\n",
 "### 8.1.3 Cước phí / gộp hàng LCL / kế toán / công nợ\n\nNhóm này tập hợp các quyết định về cước phí, gộp xe và gộp hàng LCL, khai chi phí, định dạng tiền cùng các trang kế toán – công nợ; mỗi dòng ghi ngày ra quyết định, nội dung chốt và phạm vi áp dụng.\n\n"),
("### 8.1.4 Lái xe / Driver app\n\n",
 "### 8.1.4 Lái xe / Driver app\n\nNhóm này tập hợp các quyết định cho ứng dụng lái xe, từ hiển thị mã chuyến, yêu cầu ảnh đến trình tự giao nhận trên màn nhận lệnh.\n\n"),
("### 8.1.5 UI / form / theme\n\n",
 "### 8.1.5 UI / form / theme\n\nNhóm này tập hợp các quyết định về giao diện, biểu mẫu và theme chung của ứng dụng; phần lớn kèm nguyên văn chỉ đạo của chủ dự án.\n\n"),
("### 8.1.6 Quy trình & phát hành\n\n",
 "### 8.1.6 Quy trình & phát hành\n\nNhóm này tập hợp các quyết định về quy trình phát triển, cổng kiểm thử và cổng phát hành.\n\n"),
]
for old_h, new_h in LEADS:
    assert src.count(old_h) == 1, old_h
    src = src.replace(old_h, new_h)

open("after/spec-8.md", "w").write(src)
print(f"3-field: {n3}, ngày+đối tượng: {n2a}, ngày+quyết định: {n2b}, STT: {nstt}, hạng mục: {nhm}")
old_len = len(open("src/spec-8.md").read())
print("written", len(src), f"({len(src)/old_len*100:.1f}%)")
