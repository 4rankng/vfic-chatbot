#!/usr/bin/env python3
src = open("src/spec-7.md").read()

def cut(start_marker, end_marker):
    i = src.index(start_marker)
    j = src.index(end_marker, i)
    return src[i:j]

P = []

# B1: §7.1 five open points
old = cut("- **#:** 1\n- **Điểm còn mở:** **Xóa lô của Điều vận**", "\n\n**Điểm mở bổ sung sau 21/10")
new = """1. **Xóa lô của Điều vận**: quyết định 21/10 07:54 (Frank) **cho phép** ĐV + CUS xóa lô, Ops không; phía máy chủ vẫn chặn ("Chỉ CUS hoặc Quản trị viên"). Việc chờ: áp dụng quyền phía máy chủ.
2. **Dữ liệu đã xóa còn hiển thị**: việc chờ là quyết định chính sách dữ liệu bản thử (xóa cứng hay không).
3. **(Gợi ý Hãang tàu)** + nhóm yêu cầu chờ kết quả: chưa có kết quả chốt. Việc chờ: kiểm tra lại /02/04/05/06, DIS-06/07, DRI-02, REP-01/02.
4. **Nhóm chấm công** (14/10): tài liệu ghi đạt nhưng **chưa tra được bằng chứng kiểm thử**. Việc chờ: truy bằng chứng trước khi công nhận.
5. **Phiếu không truy được bằng chứng**: nhiều phiếu nghiệm thu chỉ ghi "Đã kiểm thử đạt" của tài liệu tổng hợp (các ngày 14–18/10 và các nhóm kiểm thử riêng). Việc chờ: truy bằng chứng trước khi công nhận đạt."""
P.append((old, new))

# B2: §7.2.2 DIS
old = cut("- **Mã:** DIS-01", "\n### 7.2.3 LCL")
new = """- **DIS-01** — Bỏ chặn phím Space trong ô ghi chú điều vận (soạn thảo bình thường).
- **DIS-02** — Bỏ popup hẹn giờ khi phát lệnh → **icon phát 1 chạm**.
- **DIS-03** — Cho phép gán **cùng 1 đầu kéo cho cả 2 cont kẹp** (không chặn "trùng đầu kéo" trong chính cặp; trùng khung giờ ngoài cặp → hỏi "Vẫn lưu?").
- **DIS-04** — Bộ lọc trạng thái xe: "Chờ/Đang/Đã phân xe", "Chưa gán biển/Đã gán biển" — tách lô đã gán xe khỏi danh sách chờ.
- **DIS-05** — Nhập/sửa **"Giờ trả hàng"** ngay lúc gán biển; sửa giờ điều xe lưu là đồng bộ cột giờ + lịch trình.
- **DIS-06** — Thêm tác vụ **"Lấy Lẻ"**: vỏ rỗng → đóng hàng lẻ chuyển kho → hạ rỗng/đóng hàng hạ cảng.
- **DIS-07** — Chọn "Lấy Lẻ" bị auto-đổi "Đảo vỏ" + báo trùng/gập khung giờ sai → bỏ auto-tag, xử lý cảnh báo đúng.
- **DIS-08** — Bảng kế hoạch điều xe: **in đậm số container**, tên Cảng chuyển chữ thường (không đậm).
- **DIS-09** — Nhà xe ngoài: **phát lệnh trước khi có biển số** (CUS/điều phối cập nhật BKS + tài xế sau) — hỏi "Vẫn phát lệnh?" → BKS trống, chip chờ biển.
- **DIS-10** — **Đổi nhà xe/BKS** cho tác vụ đã phân bổ (đơn, ghép, lấy lẻ) — nút giấu sau nhãn "Lẻ · Ghép (1/N)" cột Phân loại → hộp thoại "Đổi nhà xe/BKS".

"""
P.append((old, new))

# B3: §7.2.3 LCL
old = cut("- **Mã:** LCL-01", "\n### 7.2.4 DRI")
new = """- **LCL-01** — Lô LCL ở Tổng quan bấm Chi tiết **không thấy thông tin** → sửa đồng bộ dữ liệu.
- **LCL-02** — Form **"Thêm kho lấy hàng"** tối giản như trường bãi cảng; mặc định **Nhập khẩu**, phải chọn KH; radio Xuất khẩu → hộp thoại "Thêm kho trả hàng" 3 trường gọn. **Quyết định 22/10: kho CFS = danh mục dùng chung, KHÔNG lọc theo khách hàng.**
- **LCL-03** — Bỏ trường thời gian phụ ở "Lịch & ghi chú" hàng lẻ, **chỉ giữ "Ngày giao hàng"** (FCL vẫn có section).
- **LCL-04** — Trường **Quy cách đóng gói**: gợi ý tự động (Bao/Kiện/Pallet…) + danh mục cố định; gõ tự do "Kiện gỗ" được chấp nhận.
- **LCL-05** — Đổi nhãn **"Ngày giao dự kiến" → "Ngày giao hàng"**.
- **LCL-06** — Trường **Thể tích (CBM) bắt buộc → tùy chọn** (lưu được lô lẻ khi chưa có số khối).
- **LCL-07** — Cước hàng lẻ theo **tải trọng (tấn)** + cont 20/40; gom nhiều lô lẻ 1 xe: trả nhà xe 1 chuyến gom, thu KH 1 cước gộp hoặc tách. **Quyết định 21/10 15:22:** thu theo từng lô, trả nhà xe 1 dòng/chuyến, tách không làm đổi lãi lỗ, **lãi = Σ thu − trả**.

"""
P.append((old, new))

# B4: §7.2.4 DRI
old = cut("- **Mã:** DRI-01", "\n### 7.2.5 REP")
new = """- **DRI-01** — SĐT kho/nhà máy là **hyperlink `tel:`** gọi ngay trên điện thoại (chạm để gọi cho thủ kho).
- **DRI-02** — Điều vận **tự cập nhật/bổ sung SĐT** nhà máy, bãi kho; đối tác chỉ có địa chỉ, không có SĐT → hiển thị "—" (không phải lỗi ứng dụng).
- **DRI-03** — App lái xe hiển thị **sai lộ trình/trình tự giao nhận với chuyến kẹp 2×20ft** → mỗi cont một khối riêng + nút "Sửa số cont N" riêng, cập nhật từng cont.
- **DRI-04** — Màn nhận lệnh: bãi hạ nhảy sang "Địa chỉ giao hàng", Cảng hạ báo "Chưa có nơi trả rỗng" → IMPORT không cảng hạ nhưng có điểm trả → "Cảng hạ" = tên điểm trả + ĐCH đầy đủ; EXPORT giữ luật cũ.

"""
P.append((old, new))

# B5: §7.2.5 REP + §7.2.6 ENV
old = cut("- **Mã:** REP-01", "\n\n---\n\n## 7.3") if "\n\n---\n\n## 7.3" in src else cut("- **Mã:** REP-01", "\n---\n\n## 7.3")
new = """- **REP-01** — Bảng **tổng hợp hiệu suất toàn đội theo ngày**, % cơ cấu Kẹp ghép / Kết hợp / Lấy lẻ / Chuyển kho; chế độ ngày + xuất Excel.
- **REP-02** — Báo cáo **từng đầu xe nội bộ theo chu kỳ 1 tháng**, % cơ cấu chuyến cho KPI.
- **ENV-01** — (nội dung yêu cầu để trống trong tài liệu gốc)."""
P.append((old, new))

# B6: §7.6 decision history
old = cut("- **Ngày:** 2026-09-09", "\n\n**Trạng thái chốt cuối của 2 mảng đảo chiều:**")
new = """- **09/09/2026** — 4 quyết định cước: kẹp phụ phí dầu về 0 khi giá dầu kỳ < mốc; km khứ hồi; mốc = **Ngày vận chuyển**; không hồi tố. Ảnh hưởng: REP, LCL-07.
- **14/09 và 17/09/2026** — thao tác trực tiếp, **không phê duyệt nội bộ**; cần Internet; 5 trạng thái. Ảnh hưởng: toàn ma trận.
- **20/09/2026** — ngưỡng áp khi **≥**; F=17.842,5926; 0 thật vs "—"; 4 điều kiện bảng kê; sửa nhanh lịch + ghi chú 3 vai. Ảnh hưởng: CUS, REP.
- **22/09/2026** — quy tắc hiển thị hợp nhất (bảng không cắt, một kiểu thanh lọc, màn trống, trạng thái dạng chữ, kiểm thử tự động); ĐV/Lái xe không thao tác trong hộp. Ảnh hưởng: CUS/DIS/REP.
- **01/10/2026** (220/245/252) — **giữ** phạm vi CUS danh mục phí; số trường **không âm**; lô **DRAFT** — **không submit/bước duyệt**. Ảnh hưởng: CUS.
- **02/10/2026** — bỏ trường **Luồng hải quan** khỏi màn hình, giao diện và cơ sở dữ liệu. Ảnh hưởng: /06.
- **05/10/2026** — "Quỹ TM"→"Quỹ tiền mặt"; cảng sau điều xe; Phí nhiên liệu; **Lấy Lẻ không tự ĐẢO VỎ**. Ảnh hưởng: DIS-07.
- **21/10/2026 07:54 (Frank)** — **CUS + ĐV được xóa lô, Ops không**; nút "Xóa lô" trên Kế hoạch Chi tiết Xe ĐV GIỮ. Ảnh hưởng: chính sách xóa lô — **chờ áp dụng → còn mở**.
- **21/10/2026 11:26** — thêm cont copy **KỂ CẢ Loại cont**. Quyết định này bị hủy 22/10.
- **21/10/2026 15:22** — **LCL-07**: thu theo từng lô, trả 1 dòng/chuyến, không làm đổi lãi lỗ, lãi = Σ thu − trả; KHÔNG phân bổ tỷ lệ/fit-line/bảng giá ngoài 5T-3.5T. Ảnh hưởng: LCL-07 và các yêu cầu liên quan.
- **21/10/2026** — chi phí vừa tạo sửa/xóa tới khi chốt sổ; hiển thị theo tấn.
- **22/10/2026 09:50 (Zalo)** — **bật lại nút Thêm/Xóa @Chi tiết**; quyết định 17/10 hết hiệu lực.
- **22/10/2026** — làm rõ: tờ khai sửa ngay tại Chi tiết + sync mọi cont.
- **22/10/2026** — **bỏ mã chuyến khỏi app lái xe** (đảo quyết định cũ); **e-POD ảnh tùy chọn**. Ảnh hưởng: DRI và các yêu cầu liên quan.
- **23/10/2026** — gộp hàng: tách chi phí nhóm (ĐV) vs doanh thu nhóm (CUS); 100/0 chỉ trong nhóm gộp CUS — **chỉ ghi tài liệu**. Ảnh hưởng: LCL-07 — **Còn mở — chưa chốt**.
- **24/10/2026** — lần đảo thứ 3: **XNK trước Số Bill/Booking, Số tờ khai xuống cuối** — **Còn mở — chưa chốt**.
- **26/10/2026** — lọc ngày Chi tiết bỏ cont chưa có ngày; "chưa có ngày" chỉ ở Tổng quan. Ảnh hưởng: CUS/LCL.
- **26/10/2026** — tờ khai **theo cont**, bỏ nhập cấp lô, không chặn trùng số — **Còn mở — chưa chốt**."""
P.append((old, new))

# B7: §7.8 A stats
old = cut("- - **Số:** **22**", "\n\n*(DIS-08 tách riêng")
new = """- **Đã triển khai: 22 yêu cầu** — DIS-01, DIS-02, DIS-03, DIS-04, DIS-05, DIS-09, DIS-10, LCL-01, LCL-02, LCL-03, LCL-04, LCL-05, LCL-06, LCL-07, DRI-01, DRI-03, DRI-04, ENV-01 (một số vị trí mã để trống trong tài liệu gốc).
- **Đã triển khai, cần kiểm tra lại: 11 yêu cầu** — DIS-06, DIS-07, DIS-08, DRI-02, REP-01, REP-02 (một số vị trí mã để trống trong tài liệu gốc).
- **Còn mở — chờ chốt: 2 yêu cầu** (mã để trống trong tài liệu gốc).
- **Tổng: 35 yêu cầu** — CUS 11 + DIS 10 + LCL 7 + DRI 4 + REP 2 + ENV 1."""
P.append((old, new))

# B8: §7.8 B stats
old = cut("- - **Số:** **13**", "\n\n**C. Điểm Còn mở")
new = """- **Đã triển khai: 13** — 04, 06, 07, 08, 11, 14, 15, 16, 17, 18, 19, 20 (một số vị trí mã để trống trong tài liệu gốc).
- **Đã triển khai, cần kiểm tra lại: 7** — 03, 05, 09, 10, 12, 13 (một số vị trí mã để trống trong tài liệu gốc).
- **Còn mở — chờ chốt: 1** (đối chiếu quyết định 26/10).
- **Đã hủy/thay thế: 2** (cả hai thay thế ngày 22/10).
- **Tổng: 23**."""
P.append((old, new))

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
open("after/spec-7.md", "w").write(src)
print("written", len(src))
