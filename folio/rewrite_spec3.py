#!/usr/bin/env python3
src = open("src/spec-3.md").read()

P = []

# Block 1: §3.2.1 band layout
P.append((
"""- **Band:** 1
- **Nội dung:** **Khách hàng · Hình thức xuất nhập khẩu**

- **Band:** 2
- **Nội dung:** **Số Bill/Booking · Hãng tàu (chỉ FCL)**

- **Band:** 3
- **Nội dung:** **Tuỳ chọn** (Lệnh chạy ngoài · Có cược container · Đóng kết hợp) — full width

- **Band:** 4 (cuối)
- **Nội dung:** ~~Số tờ khai~~ — **ô nhập bị gỡ theo quyết định ngày 26/10, xem 3.4**""",
"""Bố cục gồm 4 band phẳng: band 1 là **Khách hàng · Hình thức xuất nhập khẩu**; band 2 là **Số Bill/Booking · Hãng tàu** (hãng tàu chỉ hiện với FCL); band 3 là nhóm **tuỳ chọn** (Lệnh chạy ngoài · Có cược container · Đóng kết hợp) trải full width; band 4 cuối trang vốn chứa Số tờ khai nhưng ô nhập này đã bị gỡ theo quyết định ngày 26/10 (xem 3.4)."""))

# Block 2: §3.2.3 mandatory counter modes
P.append((
"""- **Chế độ:** Form trống
- **Mẫu số:** 0/9

- **Chế độ:** FCL 1 cont, đủ nhận diện
- **Mẫu số:** 3/9
- **Thành phần:** 9 = 3 nhận diện (Khách hàng · Hình thức XNK · Số Bill/Booking) + Loại cont + Nhà máy + Tuyến + Cảng nâng + Cảng hạ + Ngày giờ đóng/trả

- **Chế độ:** Hàng lẻ
- **Mẫu số:** 3/10
- **Thành phần:** + ô **Kho (CFS/Cảng)**

- **Chế độ:** Lệnh chạy ngoài
- **Mẫu số:** 3/7
- **Thành phần:** Miễn điều kiện danh mục""",
"""- Form trống: mẫu số là 0/9.
- FCL 1 cont đã đủ nhận diện: 3/9, trong đó mẫu số 9 = 3 nhận diện (Khách hàng · Hình thức XNK · Số Bill/Booking) + Loại cont + Nhà máy + Tuyến + Cảng nâng + Cảng hạ + Ngày giờ đóng/trả.
- Hàng lẻ: 3/10 — mẫu số cộng thêm ô **Kho (CFS/Cảng)**.
- Lệnh chạy ngoài: 3/7 — miễn điều kiện danh mục."""))

# Block 3: §3.4.2 history
P.append((
"""- **Ngày:** (gốc)
- **Quyết định:** : *"Nhiều tờ khai trên 1 lô; thêm số tờ khai cho 1 cont → đồng bộ tất cả cont"*
- 
- **Ngày:** 02/10
- **Quyết định:** Bỏ trường **Luồng hải quan** khỏi màn hình + giao diện lập trình + cơ sở dữ liệu (*"there's no such thing"*)
- 
- **Ngày:** 13/10
- **Quyết định:** Tờ khai từ thực thể cấp lô → **theo từng container** + tự copy (thay quy định trước đó)
- 
- **Ngày:** 22/10
- **Quyết định:** làm rõ: sửa/thêm **trực tiếp tại Chi tiết lô**, nhập 1 cont → đồng bộ
- 
- **Ngày:** 24/10
- **Quyết định:** Quyết định B: Số tờ khai **band cuối** phần Nhận diện lô
- 
- **Ngày:** **26/10**
- **Quyết định:** **Quyết định ngày 26/10: theo từng container · không chặn trùng · sửa từng cont · bỏ nhập cấp lô**
- """,
"""- Ban đầu (không ghi ngày): *"Nhiều tờ khai trên 1 lô; thêm số tờ khai cho 1 cont → đồng bộ tất cả cont"*.
- Ngày 02/10: bỏ trường **Luồng hải quan** khỏi màn hình, giao diện lập trình và cơ sở dữ liệu (*"there's no such thing"*).
- Ngày 13/10: tờ khai chuyển từ thực thể cấp lô sang **theo từng container** kèm cơ chế tự copy (thay quy định trước đó).
- Ngày 22/10: làm rõ — sửa/thêm **trực tiếp tại Chi tiết lô**, nhập 1 cont thì đồng bộ.
- Ngày 24/10: quyết định B — Số tờ khai đặt ở **band cuối** phần Nhận diện lô.
- **Ngày 26/10 (hiện hành):** theo từng container · không chặn trùng · sửa từng cont · bỏ nhập cấp lô."""))

# Block 4: §3.5.2 document catalog
P.append((
"""- **Nhóm:** FCL — e-POD
- **Chứng từ:** ① **Phiếu hạ bãi/trả hàng** ② **Biên bản giao nhận** (dấu/chữ ký)
- **Bắt buộc?:** **Bắt buộc 2 nhóm**

- **Nhóm:** Ảnh thao tác (container/chì/e-POD)
- **Chứng từ:** Ảnh tải lên
- **Bắt buộc?:** **TÙY CHỌN** — nhận lệnh và hoàn thành với **0 ảnh** được; nhãn "Tùy chọn / Chưa có"
- **Căn cứ:** Quyết định ngày 22/10/2026

- **Nhóm:** LCL
- **Chứng từ:** Bộ chứng từ thay "phiếu hạ container"
- **Bắt buộc?:** **Chưa chốt** — cấm áp bộ FCL

- **Nhóm:** Chi phí/Ops
- **Chứng từ:** Ảnh chụp biên lai khi khai chi phí
- **Bắt buộc?:** **TÙY CHỌN**: *"Có thể chụp hoặc không, không ghi nhận thiếu chứng từ"*

- **Nhóm:** Nhóm có hóa đơn
- **Chứng từ:** **Số hóa đơn thật** cho nhóm *yêu cầu hóa đơn*
- **Bắt buộc?:** Bắt buộc ở đường phê duyệt, không nhận bằng chứng thay thế""",
"""- **FCL — e-POD** gồm 2 nhóm **bắt buộc**: ① **Phiếu hạ bãi/trả hàng** và ② **Biên bản giao nhận** (có dấu/chữ ký).
- **Ảnh thao tác** (container/chì/e-POD) là ảnh tải lên, mang tính **tùy chọn** — nhận lệnh và hoàn thành với **0 ảnh** vẫn được; nhãn hiển thị "Tùy chọn / Chưa có" (quyết định ngày 22/10/2026).
- **LCL**: dùng bộ chứng từ thay "phiếu hạ container" — **chưa chốt**, nhưng cấm áp bộ chứng từ của FCL.
- **Chi phí/Ops**: ảnh chụp biên lai khi khai chi phí là **tùy chọn**: *"Có thể chụp hoặc không, không ghi nhận thiếu chứng từ"*.
- **Nhóm có hóa đơn**: yêu cầu **số hóa đơn thật** cho nhóm *yêu cầu hóa đơn* — bắt buộc ở đường phê duyệt, không nhận bằng chứng thay thế."""))

# Block 5: §3.6.2 comparison (broken labels)
P.append((
"""- **:** Nhóm tiền
- ****ĐV — gộp xe (trả nhà xe)**:** `cost_group_id`
- ****CUS — gộp hàng (thu khách)**:** `rev_group_id` — **độc lập hoàn toàn**

- **:** Luật tiền
- ****ĐV — gộp xe (trả nhà xe)**:** Lô 1 = **100%** cước trả, Lô 2..N = **0₫** (1 khoản/chuyến)
- ****CUS — gộp hàng (thu khách)**:** Mặc định **per-lot** (đơn giá Tuyến × KH × loại xe từng lô); **100%/0₫ chỉ trong nhóm gộp CUS chủ động**

- **:** Popup
- ****ĐV — gộp xe (trả nhà xe)**:** 4 trường (sau 23/10): Loại xe tính cước trả\\* · Nhà xe\\* · BKS thực\\* · Cước trả ĐVVC (trống = tra bảng giá; nhập tay = lấy giá nhập)
- ****CUS — gộp hàng (thu khách)**:** Per-lot 3 trường/lô: Loại xe thu · Giá cước thu · BKS báo khách (trống → lấy BKS thực). Ghép: loại xe thu chung · BKS ảo chung · cước Lô 1

- **:** Ràng buộc
- ****ĐV — gộp xe (trả nhà xe)**:** Xe tải → **100% xe ngoài (nhà thầu)**; Cont 20'/40' → nội bộ SilverSea **hoặc** ngoài
- ****CUS — gộp hàng (thu khách)**:** **Chỉ ghép cùng 1 khách hàng** — khác KH → chặn

- **:** Ghi chú
- ****ĐV — gộp xe (trả nhà xe)**:** `Lẻ · Ghép (k/N)`
- ****CUS — gộp hàng (thu khách)**:** `Ghép thu cước cùng Lô 1`; trên Debit Note: `Ghép xe cùng Bill <Bill Lô 1>`""",
"""- **Nhóm tiền**: gộp xe trả nhà xe dùng `cost_group_id`; gộp hàng thu khách dùng `rev_group_id` — hai nhóm **độc lập hoàn toàn**.
- **Luật tiền**: gộp xe (điều vận) tính Lô 1 = **100%** cước trả, Lô 2..N = **0₫** (1 khoản/chuyến); gộp hàng (CUS) mặc định **per-lot** (đơn giá Tuyến × KH × loại xe của từng lô), **100%/0₫ chỉ áp trong nhóm gộp CUS chủ động**.
- **Popup**: gộp xe (điều vận) gồm 4 trường (sau 23/10): Loại xe tính cước trả\\* · Nhà xe\\* · BKS thực\\* · Cước trả ĐVVC (trống = tra bảng giá; nhập tay = lấy giá nhập); gộp hàng (CUS) per-lot 3 trường/lô: Loại xe thu · Giá cước thu · BKS báo khách (trống → lấy BKS thực); khi ghép thì loại xe thu chung · BKS ảo chung · cước theo Lô 1.
- **Ràng buộc**: gộp xe (điều vận) — xe tải thì **100% xe ngoài (nhà thầu)**, cont 20'/40' thì nội bộ SilverSea **hoặc** ngoài; gộp hàng (CUS) — **chỉ ghép cùng 1 khách hàng**, khác khách hàng thì chặn.
- **Ghi chú**: gộp xe (điều vận) gắn tag `Lẻ · Ghép (k/N)`; gộp hàng (CUS) gắn `Ghép thu cước cùng Lô 1`, trên Debit Note là `Ghép xe cùng Bill <Bill Lô 1>`."""))

# Block 6: §3.7.4 classification
P.append((
"""- **Phân loại:** **FCL**
- **Dấu hiệu:** Nhãn NHẬP / XUẤT; dòng có số-cont + loại-cont
- **Ghi chú:** Thiếu số → `"Chưa có số container"` + loại + công việc + lịch, **không ẩn loại vì thiếu số**

- **Phân loại:** **LCL**
- **Dấu hiệu:** Badge **NHẬP LẺ / XUẤT LẺ** trên list + chi tiết; hiện thông số hàng/loại xe thay ô container
- **Ghi chú:** Không container giả

- **Phân loại:** **Nhóm gộp LCL**
- **Dấu hiệu:** Tag cột PHÂN LOẠI `Lẻ · Ghép (k/N)`
- **Ghi chú:** Tag vỡ layout = lỗi đang mở

- **Phân loại:** **Cặp vận tải**
- **Dấu hiệu:** Nhãn **KẸP / KẾT HỢP** cạnh đúng công việc; bỏ ghép → nhãn mất, trạng thái từng container vẫn đọc được
- **Ghi chú:** Phân loại ghép ≠ trạng thái vận hành

- **Phân loại:** **4 tác vụ điều xe**
- **Dấu hiệu:** **Đi đơn · Đi kết hợp · Đi kẹp (2×20FT) · Lấy lẻ**""",
"""- **FCL** nhận biết qua nhãn NHẬP / XUẤT; dòng có số-cont + loại-cont. Khi thiếu số thì hiển thị `"Chưa có số container"` cùng loại + công việc + lịch — **không ẩn loại vì thiếu số**.
- **LCL** nhận biết qua badge **NHẬP LẺ / XUẤT LẺ** trên danh sách và chi tiết; hiển thị thông số hàng/loại xe thay cho ô container, và không dùng container giả.
- **Nhóm gộp LCL** mang tag ở cột PHÂN LOẠI dạng `Lẻ · Ghép (k/N)`; tag làm vỡ layout là lỗi đang mở.
- **Cặp vận tải** có nhãn **KẸP / KẾT HỢP** cạnh đúng công việc; khi bỏ ghép thì nhãn mất nhưng trạng thái từng container vẫn đọc được. Lưu ý phân loại ghép ≠ trạng thái vận hành.
- **4 tác vụ điều xe** là: **Đi đơn · Đi kết hợp · Đi kẹp (2×20FT) · Lấy lẻ**."""))

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
open("after/spec-3.md", "w").write(src)
print("written", len(src))
