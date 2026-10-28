#!/usr/bin/env python3
src = open("src/spec-5.md").read()

P = []

P.append((
"""- **Ký hiệu:** `I`
- **Tên:** Giá gốc
- **Bản chất:** Trước chia sẻ và phụ phí dầu
- **Đổi khi nào:** Chỉ khi đàm phán lại hợp đồng

- **Ký hiệu:** `% chia sẻ`
- **Tên:** Tỷ lệ chia sẻ
- **Bản chất:** Thuộc cặp **khách hàng – tuyến**
- **Đổi khi nào:** Theo hợp đồng

- **Ký hiệu:** `J`
- **Tên:** Cước chia sẻ = `I × (1 + % chia sẻ)`
- **Bản chất:** **TĨNH**
- **Đổi khi nào:** Chỉ khi đổi `I` hoặc `% chia sẻ`

- **Ký hiệu:** `H`
- **Tên:** Phụ phí dầu
- **Bản chất:** **ĐỘNG** theo kỳ giá dầu
- **Đổi khi nào:** Mỗi kỳ áp giá

- **Ký hiệu:** `K`
- **Tên:** Cước cuối = `J + H`
- **Bản chất:** Kết quả tính
- **Đổi khi nào:** Tự tính

- **Ký hiệu:** `L`
- **Tên:** Kiểm tra = `K − J`
- **Bản chất:** **Luôn bằng `H`** — kiểm tra ngược, không phải phí thứ ba
- **Đổi khi nào:** Tự tính""",
"""- `I` là **giá gốc** — giá trước chia sẻ và trước phụ phí dầu, chỉ đổi khi đàm phán lại hợp đồng.
- `% chia sẻ` là **tỷ lệ chia sẻ**, thuộc cặp **khách hàng – tuyến**, đổi theo hợp đồng.
- `J` là **cước chia sẻ** = `I × (1 + % chia sẻ)`; đây là thành phần **TĨNH**, chỉ đổi khi `I` hoặc `% chia sẻ` đổi.
- `H` là **phụ phí dầu**; thành phần **ĐỘNG** theo kỳ giá dầu, tính lại ở mỗi kỳ áp giá.
- `K` là **cước cuối** = `J + H`; là kết quả tính, tự tính lại.
- `L` là phép **kiểm tra** = `K − J`, **luôn bằng `H`** — chỉ dùng để kiểm tra ngược, không phải phí thứ ba, tự tính."""))

P.append((
"""- **Nhóm:** **PHẢI THU**
- **Cột:** Cước thu auto · Lạch Huyện auto · Phụ phí auto · Phát sinh (CUS) · Tổng thu
- **Nguồn:** Bảng giá thu khách + tự tính

- **Nhóm:** **PHẢI TRẢ**
- **Cột:** Cước trả ĐV · Lạch Huyện (điều vận) · Phát sinh (điều vận) · Tổng 1 · Phí RU
- **Nguồn:** Bảng giá trả nhà xe + khai báo""",
"""- Nhóm **PHẢI THU** gồm các cột Cước thu auto · Lạch Huyện auto · Phụ phí auto · Phát sinh (CUS) · Tổng thu; dữ liệu lấy từ bảng giá thu khách và phần tự tính.
- Nhóm **PHẢI TRẢ** gồm các cột Cước trả ĐV · Lạch Huyện (điều vận) · Phát sinh (điều vận) · Tổng 1 · Phí RU; dữ liệu lấy từ bảng giá trả nhà xe và phần khai báo."""))

P.append((
"""- **Tuyến (nhà máy đích):** Hải Phòng – NEWEB
- **KM 1 chiều:** 130
- **KM 2 chiều:** 260
- **% chia sẻ:** **2%**
- **Hệ số J:** ×1,02

- **Tuyến (nhà máy đích):** ASKEY
- **KM 1 chiều:** 100
- **KM 2 chiều:** 200
- **% chia sẻ:** **4%**
- **Hệ số J:** ×1,04

- **Tuyến (nhà máy đích):** SUNRISE + SJ
- **KM 1 chiều:** 120
- **KM 2 chiều:** 240
- **% chia sẻ:** **2,5%**
- **Hệ số J:** ×1,025""",
"""- Tuyến **Hải Phòng – NEWEB**: km 1 chiều 130, km 2 chiều 260, % chia sẻ **2%**, hệ số J ×1,02.
- Tuyến **ASKEY**: km 1 chiều 100, km 2 chiều 200, % chia sẻ **4%**, hệ số J ×1,04.
- Tuyến **SUNRISE + SJ**: km 1 chiều 120, km 2 chiều 240, % chia sẻ **2,5%**, hệ số J ×1,025."""))

P.append((
"""- **Loại xe:** `D`
- **1.25T:** 0,10
- **2.5T:** 0,13
- **3.5T:** 0,13
- **5T:** 0,15
- **8T:** 0,20
- **10T:** 0,24
- **15T:** 0,30
- **CONT 20:** 0,32
- **CONT 40:** 0,35""",
"""Định mức `D` (lít/km) theo từng loại xe như sau: 1.25T = 0,10; 2.5T = 0,13; 3.5T = 0,13; 5T = 0,15; 8T = 0,20; 10T = 0,24; 15T = 0,30; CONT 20 = 0,32; CONT 40 = 0,35."""))

P.append((
"""- **Loại xe:** 1.25T
- **NEWEB:** 1.300.000
- **ASKEY:** 1.200.000
- **SUNRISE+SJ:** 1.300.000

- **Loại xe:** 2.5T
- **NEWEB:** 1.700.000
- **ASKEY:** 1.600.000
- **SUNRISE+SJ:** 1.700.000

- **Loại xe:** 3.5T
- **NEWEB:** 1.800.000
- **ASKEY:** 1.700.000
- **SUNRISE+SJ:** 1.800.000

- **Loại xe:** 5T
- **NEWEB:** 2.400.000
- **ASKEY:** 2.300.000
- **SUNRISE+SJ:** 2.400.000

- **Loại xe:** 8T
- **NEWEB:** 2.900.000
- **ASKEY:** 2.800.000
- **SUNRISE+SJ:** 2.900.000

- **Loại xe:** 10T
- **NEWEB:** 3.100.000
- **ASKEY:** 3.000.000
- **SUNRISE+SJ:** 3.100.000

- **Loại xe:** **15T**
- **NEWEB:** **thiếu**
- **ASKEY:** **thiếu**
- **SUNRISE+SJ:** **thiếu**

- **Loại xe:** CONT 20
- **NEWEB:** 3.900.000
- **ASKEY:** 3.800.000
- **SUNRISE+SJ:** 3.900.000

- **Loại xe:** CONT 40
- **NEWEB:** 4.100.000
- **ASKEY:** 4.000.000
- **SUNRISE+SJ:** 4.100.000""",
"""Giá gốc `I` (đ, chưa chia sẻ) theo từng loại xe như sau: loại 1.25T — NEWEB 1.300.000, ASKEY 1.200.000, SUNRISE+SJ 1.300.000; loại 2.5T — NEWEB 1.700.000, ASKEY 1.600.000, SUNRISE+SJ 1.700.000; loại 3.5T — NEWEB 1.800.000, ASKEY 1.700.000, SUNRISE+SJ 1.800.000; loại 5T — NEWEB 2.400.000, ASKEY 2.300.000, SUNRISE+SJ 2.400.000; loại 8T — NEWEB 2.900.000, ASKEY 2.800.000, SUNRISE+SJ 2.900.000; loại 10T — NEWEB 3.100.000, ASKEY 3.000.000, SUNRISE+SJ 3.100.000; loại **15T** — **thiếu** ở cả NEWEB, ASKEY và SUNRISE+SJ; loại CONT 20 — NEWEB 3.900.000, ASKEY 3.800.000, SUNRISE+SJ 3.900.000; loại CONT 40 — NEWEB 4.100.000, ASKEY 4.000.000, SUNRISE+SJ 4.100.000."""))

ok = True
for i, (old, new) in enumerate(P):
    n = src.count(old)
    if n != 1:
        print(f"BLOCK {i+1}: found {n} times — ABORT")
        ok = False
if not ok:
    import sys; sys.exit(1)
for i, (old, new) in enumerate(P):
    src = src.replace(old, new)
    print(f"block {i+1} replaced")
open("after/spec-5.md", "w").write(src)
print("written", len(src))
