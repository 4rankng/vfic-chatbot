# 7. Ma trận yêu cầu chính thức

**Quy tắc đọc:**

- Tài liệu đặc tả **đang áp dụng** là căn cứ; nhật ký thay đổi chỉ ghi *khi nào/vì sao*. Khi nguồn khác quy tắc đã chốt → **quyết định đã chốt thắng**. Mã số yêu cầu **giữ nguyên** theo tài liệu, không đánh số lại; mục "còn mở" ở §7.1 kèm hành vi tạm thời, không tự đặt điều khoản lấp chỗ trống.
- Trạng thái ghi theo chuẩn bốn mức sau: **Đã triển khai** (đã áp dụng, có bằng chứng nghiệm thu) · **Đã triển khai, cần kiểm tra lại** (đã áp dụng nhưng chưa có kết quả nghiệm thu chốt) · **Đã hủy/thay thế (ngày)** (quyết định mới hơn đảo) · **Còn mở — chờ chốt** (tài liệu ghi còn mở — **không tự đặt điều kiện nghiệm thu**).

---

## 7.1 Còn mở — chưa chốt (5 mục)

5 điểm tài liệu ghi còn mở tại thời điểm chốt 21–22/10/2026 — phải ghi **Còn mở — chưa chốt** trong mọi ma trận cho tới khi có quyết định chính thức.

1. **Xóa lô của Điều vận**: quyết định 21/10 07:54 (Frank) **cho phép** ĐV + CUS xóa lô, Ops không; phía máy chủ vẫn chặn ("Chỉ CUS hoặc Quản trị viên"). Việc chờ: áp dụng quyền phía máy chủ.
2. **Dữ liệu đã xóa còn hiển thị**: việc chờ là quyết định chính sách dữ liệu bản thử (xóa cứng hay không).
3. **(Gợi ý Hãang tàu)** + nhóm yêu cầu chờ kết quả: chưa có kết quả chốt. Việc chờ: kiểm tra lại /02/04/05/06, DIS-06/07, DRI-02, REP-01/02.
4. **Nhóm chấm công** (14/10): tài liệu ghi đạt nhưng **chưa tra được bằng chứng kiểm thử**. Việc chờ: truy bằng chứng trước khi công nhận.
5. **Phiếu không truy được bằng chứng**: nhiều phiếu nghiệm thu chỉ ghi "Đã kiểm thử đạt" của tài liệu tổng hợp (các ngày 14–18/10 và các nhóm kiểm thử riêng). Việc chờ: truy bằng chứng trước khi công nhận đạt.

**Điểm mở bổ sung sau 21/10 (vẫn là "còn mở", không tự đặt điều kiện nghiệm thu):**

- **Ma trận thứ tự nhập liệu** —  "đạt có điều kiện nhập" → **Còn mở — chưa chốt**.
- **Xóa lô ĐV** (chờ áp dụng, mục 1) và **nhóm chấm công** (chưa tra bằng chứng, mục 4) → **Còn mở — chưa chốt**.
- **Tạo khung giá qua giao diện vẫn còn lỗi** — điểm còn lại sau kiểm thử 22/10 về khoảng trễ cước (phần nghiệp vụ đã đạt, phần giao diện còn lỗi) → đang điều tra.
- **Quyết định 26/10 về tờ khai cấp lô** đối chiếu /22 — quyết định 26/10 "bỏ nhập tờ khai cấp lô, sửa từng cont" ghi đè hành vi "sync mọi cont" của , chưa được tài liệu đặc tả cập nhật → **Còn mở — chưa chốt** đối chiếu.

---

## 7.2 Ma trận 35 YC chính thức

### 7.2.1 CUS — Chứng từ / nhập lô (11 YC)

| Mã | Yêu cầu (tóm tắt) | Trạng thái |
| Mã | Yêu cầu (tóm tắt) | Trạng thái |
|---|---|---|
| CUS-01 | Gõ đủ 2 số giờ → focus tự sang ô phút, không rơi phím số; vẫn cho nhập tay/chọn lịch được. | **Đã triển khai, cần kiểm tra lại** — đạt có điều kiện về thứ tự nhập liệu; **còn mở — chờ chốt** |
| CUS-02 | Enter ở form sửa ngày giờ lô chưa có lịch = **lưu + thoát về danh sách** (không đứng ở popup). | **Đã triển khai, cần kiểm tra lại** — đã sửa nguyên nhân: 2 nút gửi nằm ngoài biểu mẫu; nhiều lần kiểm trước chưa đạt |
| CUS-03 | Nút "Copy thời gian" gán ngày giao chung cho **mọi cont** của lô nhiều cont (không nhập tay từng cont). | **Đã triển khai** — đã kiểm đạt; từng gặp lỗi nút biến mất ở 2 lần (11/10, 13/10) |
| CUS-04 | TAB từ ô "Số cont" sang "Loại cont" rồi gõ phải **mở dropdown gợi ý** (không bắt buộc click). | **Đã triển khai, cần kiểm tra lại** — chưa có kết quả chốt (REQ-09) |
| CUS-05 | Nhiều tờ khai trên một lô; thêm số tờ khai 1 cont → sync mọi cont; sửa/thêm ngay màn chi tiết. **Quyết định 22/10: sửa ngay tại Chi tiết + sync mọi cont.** | **Đã triển khai, cần kiểm tra lại** — kiểm tra giai đầu đạt, từng2 lần kiểm chưa đạt đã đóng; **còn mở — chờ chốt** đối chiếu quyết định 26/10 |
| CUS-06 | Tờ khai hải quan nhập rồi bấm hoàn tất **không lưu dữ liệu** → sửa để lưu được. | **Đã triển khai, cần kiểm tra lại** — đã sửa để lưu được, chờ kết quả chốt |
| CUS-07 | Form nhập liệu chỉ gọn **tên nhà máy** + nút "Xem chi tiết" mở địa chỉ đầy đủ + info xuất hóa đơn. | **Đã triển khai** — chưa có kết quả kiểm tra riêng (REQ-10) |
| CUS-08 | Bỏ 2 số 0 thập phân vô nghĩa sau phẩy — **đi xa hơn: hiển thị theo TẤN** (18.500 kg → "18,5 tấn"; mọi màn kg→tấn, ô nhập vẫn kg). | **Đã triển khai** — quyết định 21/10; nguyên nhân trước: dấu chấm nghìn bị đọc nhầm thành thập phân |
| CUS-09 | Sửa số lượng cont: bổ sung cont mới tự copy trường chung, **chỉ trống Số cont + Loại cont** ("Chưa chọn"). | **Đã hủy/thay thế (22/10)** — hủy quyết định 21/10, quay về nguyên văn A.1: copy Tuyến/Nhà xe/Nâng/Hạ/Trọng lượng/Giờ hẹn; không nút ở Chi tiết |
| CUS-10 | Nút **"Xóa cont"** trực tiếp trong bảng Chi tiết lô CUS. | **Đã hủy/thay thế (22/10)** — quyết định 17/10 hết hiệu lực; ngày 22/10 09:50 **mở lại** nút @Chi tiết — chờ triển khai + gỡ kiểm thử ghim cũ; ngăn Tổng quan giữ nguyên |
| CUS-11 | Thứ tự chứng từ chuẩn (quyết định 22/10): **BILL/BOOKING → SỐ TỜ KHAI → NHẬP/XUẤT → HÃNG TÀU** (ô đầu chốt là BILL/BOOKING, không chỉ "Số booking" như đặc tả A.3 cũ). | **Đã triển khai** — kiểm tra đạt ở môi trường thử nghiệm; từng 3 lần kiểm chưa đạt vì 3 màn trùng tên |

> **Lưu ý chồng lấn 22–26/10 (ảnh hưởng CUS-05/09/11):** quyết định 26/10: tờ khai **theo cont, bỏ nhập cấp lô**; quyết định 24/10 đảo XNK ↔ Bill/Booking lần 3 → **XNK cạnh KH → Bill/Booking ở mức 2 → Số tờ khai ở mức cuối**; phiếu "Sửa lô" dùng lại form Tạo lô. Ngoài ma trận đã chốt 21–22/10 → **Còn mở — chưa chốt** trước khi chốt tiêu chí nghiệm thu.

> **Lưu ý chồng lấn 22–26/10 (ảnh hưởng /09/11):** quyết định 26/10: tờ khai **theo cont, bỏ nhập cấp lô**; quyết định 24/10 đảo XNK ↔ Bill/Booking lần 3 → **XNK cạnh KH → Bill/Booking ở mức 2 → Số tờ khai ở mức cuối**; phiếu "Sửa lô" dùng lại form Tạo lô. Ngoài ma trận đã chốt 21–22/10 → **Còn mở — chưa chốt** trước khi chốt tiêu chí nghiệm thu.

### 7.2.2 DIS — Điều vận / điều phối (10 YC)

- **DIS-01** — Bỏ chặn phím Space trong ô ghi chú điều vận (soạn thảo bình thường).
- **DIS-02** — Bỏ popup hẹn giờ khi phát lệnh → **icon phát 1 chạm**.
- **DIS-03** — Cho phép gán **cùng 1 đầu kéo cho cả 2 cont kẹp** (không chặn "trùng đầu kéo" trong chính cặp; trùng khung giờ ngoài cặp → hỏi "Vẫn lưu?").
- **DIS-04** — Bộ lọc trạng thái xe: "Chờ/Đang/Đã phân xe", "Chưa gán biển/Đã gán biển" — tách lô đã gán xe khỏi danh sách chờ.
- **DIS-05** — Nhập/sửa **"Giờ trả hàng"** ngay lúc gán biển; sửa giờ điều xe lưu là đồng bộ cột giờ + lịch trình.
- **DIS-06** — Thêm tác vụ **"Lấy Lẻ"**: vỏ rỗng → đóng hàng lẻ chuyển kho → hạ rỗng/đóng hàng hạ cảng.
- **DIS-07** — Chọn "Lấy Lẻ" bị auto-đổi "Đảo vỏ" + báo trùng/gập khung giờ sai → bỏ auto-tag, xử lý cảnh báo đúng.
- **DIS-08** — Bảng kế hoạch điều xe: **in đậm số container**, tên Cảng chuyển chữ thường (không đậm).
- **DIS-09** — Nhà xe ngoài: **phát lệnh trước khi có biển số** (CUS/điều phối cập nhật BKS + tài xế sau) — hỏi "Vẫn phát lệnh?" → BKS trống, chip chờ biển.
- **DIS-10** — **Đổi nhà xe/BKS** cho tác vụ đã phân bổ (đơn, ghép, lấy lẻ) — nút giấu sau nhãn "Lẻ · Ghép (1/N)" cột Phân loại → hộp thoại "Đổi nhà xe/BKS".


### 7.2.3 LCL — Hàng lẻ (7 YC)

- **LCL-01** — Lô LCL ở Tổng quan bấm Chi tiết **không thấy thông tin** → sửa đồng bộ dữ liệu.
- **LCL-02** — Form **"Thêm kho lấy hàng"** tối giản như trường bãi cảng; mặc định **Nhập khẩu**, phải chọn KH; radio Xuất khẩu → hộp thoại "Thêm kho trả hàng" 3 trường gọn. **Quyết định 22/10: kho CFS = danh mục dùng chung, KHÔNG lọc theo khách hàng.**
- **LCL-03** — Bỏ trường thời gian phụ ở "Lịch & ghi chú" hàng lẻ, **chỉ giữ "Ngày giao hàng"** (FCL vẫn có section).
- **LCL-04** — Trường **Quy cách đóng gói**: gợi ý tự động (Bao/Kiện/Pallet…) + danh mục cố định; gõ tự do "Kiện gỗ" được chấp nhận.
- **LCL-05** — Đổi nhãn **"Ngày giao dự kiến" → "Ngày giao hàng"**.
- **LCL-06** — Trường **Thể tích (CBM) bắt buộc → tùy chọn** (lưu được lô lẻ khi chưa có số khối).
- **LCL-07** — Cước hàng lẻ theo **tải trọng (tấn)** + cont 20/40; gom nhiều lô lẻ 1 xe: trả nhà xe 1 chuyến gom, thu KH 1 cước gộp hoặc tách. **Quyết định 21/10 15:22:** thu theo từng lô, trả nhà xe 1 dòng/chuyến, tách không làm đổi lãi lỗ, **lãi = Σ thu − trả**.


### 7.2.4 DRI — Lái xe (4 YC)

- **DRI-01** — SĐT kho/nhà máy là **hyperlink `tel:`** gọi ngay trên điện thoại (chạm để gọi cho thủ kho).
- **DRI-02** — Điều vận **tự cập nhật/bổ sung SĐT** nhà máy, bãi kho; đối tác chỉ có địa chỉ, không có SĐT → hiển thị "—" (không phải lỗi ứng dụng).
- **DRI-03** — App lái xe hiển thị **sai lộ trình/trình tự giao nhận với chuyến kẹp 2×20ft** → mỗi cont một khối riêng + nút "Sửa số cont N" riêng, cập nhật từng cont.
- **DRI-04** — Màn nhận lệnh: bãi hạ nhảy sang "Địa chỉ giao hàng", Cảng hạ báo "Chưa có nơi trả rỗng" → IMPORT không cảng hạ nhưng có điểm trả → "Cảng hạ" = tên điểm trả + ĐCH đầy đủ; EXPORT giữ luật cũ.


### 7.2.5 REP — Báo cáo (2 YC)

- **REP-01** — Bảng **tổng hợp hiệu suất toàn đội theo ngày**, % cơ cấu Kẹp ghép / Kết hợp / Lấy lẻ / Chuyển kho; chế độ ngày + xuất Excel.
- **REP-02** — Báo cáo **từng đầu xe nội bộ theo chu kỳ 1 tháng**, % cơ cấu chuyến cho KPI.

### 7.2.6 ENV — Môi trường (1 YC)

- **ENV-01** — (nội dung yêu cầu để trống trong tài liệu gốc).
---

## 7.3 REQ-01..REQ-23 — bảng đối chiếu

Bảng trạng thái yêu cầu đối chiếu ngày 21/10/2026, cập nhật quyết định 21–22/10; cột "Mã" giữ nguyên mã YC tương ứng.

| REQ | Mã | Trạng thái | Ghi chú |
| REQ | Mã | Trạng thái | Ghi chú |
|---|---|---|---|
| REQ-01 | CUS-02 | **Đã triển khai** | Enter lưu; lỗi phím không ăn ở 3 màn đã sửa |
| REQ-02 | DIS-01 | **Đã triển khai, cần kiểm tra lại** | Chưa có kết quả chốt |
| REQ-03 | DIS-02 | **Đã triển khai, cần kiểm tra lại** | Đã đổi luồng; icon 1 chạm chưa áp dụng riêng |
| REQ-04 | DIS-03 | **Đã triển khai** | Kiểm tra ghi đạt |
| REQ-05 | — | **Đã triển khai, cần kiểm tra lại** | Gợi ý hãng tàu chưa có kết quả chốt |
| REQ-06 | — | **Đã triển khai** | Chọn-all số cont + ngày mặc định (khai chi phí + tạo lô) |
| REQ-07 | — | **Đã triển khai** | Đã kiểm tra giao diện 390px trên môi trường thử nghiệm; kiểm tra phạt theo đơn vị chờ chủ trương dữ liệu · **đã thay thế 22/10**: bỏ mã chuyến khỏi app lái xe (chỉ giao diện) |
| REQ-08 | DIS-04 | **Đã triển khai** | Tab "Chưa gán xe 52 \| Đã gán xe 47" |
| REQ-09 | CUS-04 | **Đã triển khai, cần kiểm tra lại** | Sự kiện focus |
| REQ-10 | CUS-07 | **Đã triển khai, cần kiểm tra lại** | Chưa có kết quả chốt |
| REQ-11 | REP-01/02 | **Đã triển khai, cần kiểm tra lại** | Kiểm tra 2 chế độ còn mở |
| REQ-12 | DIS-06/07 | **Đã triển khai, cần kiểm tra lại** | Danh mục có Lấy Lẻ; mới áp cho luồng cont — chờ kiểm tra luồng |
| REQ-13 | DIS-05 | **Đã triển khai, cần kiểm tra lại** | "Đạt có điều kiện" — giữ mở chờ ma trận thứ tự nhập liệu |
| REQ-14 | DRI-01 | **Đã triển khai** | Chạm để gọi (`tel:`) |
| REQ-15 | DIS-09 | **Đã triển khai** | Phát lệnh chờ biển số |
| REQ-16 | LCL-02/06 | **Đã triển khai** | Thêm nhanh kho; kiểm tra đạt |
| REQ-17 | LCL-03 | **Đã triển khai** | Dọn trường; kiểm tra đạt |
| REQ-18 | DRI-04 | **Đã triển khai** | Địa chỉ cảng hạ/địa chỉ bãi hạ đúng |
| REQ-19 | LCL-07 | **Đã triển khai** | Theo quyết định 21/10 15:22 |
| REQ-20 | LCL-04 | **Đã triển khai** | Quy cách đóng gói; số khối trống vẫn lưu được |
| REQ-21 | CUS-05 | **Còn mở — chờ chốt** | Tờ khai tự sao chép đạt; quyết định 22/10: sửa ngay tại Chi tiết + nhập 1 cont sync mọi cont — đối chiếu quyết định 26/10 bỏ nhập cấp lô |
| REQ-22 | CUS-09 | **Đã hủy/thay thế (22/10)** | Hủy "copy KỂ CẢ Loại cont" (quyết định 21/10): giờ copy **tất cả trừ Số cont + Loại cont** |
| REQ-23 | CUS-10 | **Đã hủy/thay thế (22/10)** | Bật lại nút Thêm/Xóa @Chi tiết (22/10 09:50); "bỏ nút @Chi tiết" chỉ đúng tới hết 21/10; kiểm thử ghim cũ cần gỡ |

**Tổng hợp REQ-01..23:** Đã triển khai = 13 (01, 04, 06, 07, 08, 11, 14–20) · Đã triển khai, cần kiểm tra lại = 7 (02, 03, 05, 09, 10, 12, 13) · Còn mở — chờ chốt = 1 (REQ-21) · Đã hủy/thay thế = 2 (REQ-22, REQ-23).

---

**Tổng hợp ..23:** Đã triển khai = 13 (01, 04, 06, 07, 08, 11, 14–20) · Đã triển khai, cần kiểm tra lại = 7 (02, 03, 05, 09, 10, 12, 13) · Còn mở — chờ chốt = 1 () · Đã hủy/thay thế = 2 (, ).

---

## 7.4 Ghi chú nghiệp vụ theo mảng (tổng hợp nghiệm thu)

Mô tả ngắn các nội dung nghiệp vụ còn giá trị từ nghiệm thu; chi tiết kỹ thuật để ở tài liệu dev, không nêu ở đây.

- **Chứng từ / nhập lô:** khôi phục tờ khai bị mất khi thêm; chọn SĐT nhà máy có bộ chọn + hộp thoại; sao chép thời gian theo từng dòng; "Sửa lô" dùng lại biểu mẫu Tạo lô ở chế độ sửa (điền trước kể cả Hình thức XNK, gửi dạng cập nhật — hộp thoại 6 nút cũ chỉ là phương án "Sửa nhanh"); thêm cont tự copy trường chung, để trống Số cont + Loại cont (22/10); nút Thêm/Xóa tại Chi tiết bật lại (22/10), sổ cái dùng chung chi tiết lô; thêm nhanh kho lấy/trả + nhãn theo chiều; sau khi tạo FCL vào chi tiết + "Tạo lô mới"; đổi nhãn "Nơi giao/Nơi nhận" → Nâng/Hạ (hàng lẻ: Nâng/Hạ = điểm đóng/trả); cụm thao tác cuối trang tạo lô; lưu được tờ khai hải quan; gợi ý hãng tàu lưu lại; **lọc ngày ở Chi tiết dùng ngày Việt Nam (22/10)**.
- **Điều vận:** 2 cont kẹp không báo nhầm "trùng đầu kéo"; mở lô → chi tiết điều vận; hỏi lại "Vẫn lưu?" khi trùng lịch; chú cảnh báo trong bộ lọc; bảng đồng đều chiều cao; hộp thoại giờ không cắt cột GIỜ HẸN (4 bố cục × 2 ngăn); thêm nhanh BKS; phân bổ nhà xe LCL giữ lựa chọn; gán xe lẻ chọn Nhà xe+BKS từ xe ngoài; gán xe nhóm giữ lựa chọn và tự tra cước trả ĐV; phân lại xe kẹp không bị chặn "tuyến không hợp lệ" (cặp kẹp chỉ xe nội bộ — chờ chủ trương).
- **Lái xe:** banner "xe đang chạy chuyến" không lộ mã chuyến nội bộ (dùng Bill/Booking); cảng hạ/địa chỉ bãi hạ đúng; SĐT lái xe; nhãn thiếu dấu cách; khối Chứng từ giao hàng gọn ≤60px; trọng lượng không số thập phân (đóng theo ); điểm trả ≠ cảng hạ; 2 bảng chi phí lái xe.
- **Quyết định nghiệp vụ 22–23/10 chưa ghi vào ma trận chính:** e-POD ảnh **tùy chọn** (không chặn nhận lệnh/hoàn thành vì thiếu ảnh); tìm kho gõ "GLC" ra đúng GLC; gắn nhãn NHẬP LẺ/XUẤT LẺ theo hình thức hàng; **điều chỉnh luồng Gộp hàng**: tách chi phí nhóm (ĐV) vs doanh thu nhóm (CUS), hộp thoại ĐV 4 trường (bỏ BKS ảo), CUS theo lô 3 trường + [Tách nhóm], 100/0 chỉ trong nhóm gộp CUS — ghi ở tài liệu nghiệp vụ ngày 23/10 → **Còn mở — chưa chốt**.

---

## 7.5 Quyết định ảnh hưởng ma trận (truy ngược nhanh)

Bảng này chỉ liệt kê các quyết định **trực tiếp đổi chiều** một yêu cầu trong chương này; toàn bộ lịch sử ở nhật ký thay đổi.

- **09/09/2026** — 4 quyết định cước: kẹp phụ phí dầu về 0 khi giá dầu kỳ < mốc; km khứ hồi; mốc = **Ngày vận chuyển**; không hồi tố. Ảnh hưởng: REP, LCL-07.
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
- **26/10/2026** — tờ khai **theo cont**, bỏ nhập cấp lô, không chặn trùng số — **Còn mở — chưa chốt**.

**Trạng thái chốt cuối của 2 mảng đảo chiều:** nút Thêm/Xóa container @Chi tiết **BẬT LẠI** (22/10, kiểm thử ghim cũ chờ gỡ); auto-copy thêm cont = copy mọi trường **TRỪ** Số cont + Loại cont (22/10); thứ tự chứng từ form tạo lô (24/10) = **XNK cạnh KH → Bill/Booking ở mức 2 → Số tờ khai ở mức cuối**.

---

## 7.6 Thống kê tổng hợp

**A. 35 YC theo trạng thái (cập nhật 22/10):**

- **Đã triển khai: 22 yêu cầu** — DIS-01, DIS-02, DIS-03, DIS-04, DIS-05, DIS-09, DIS-10, LCL-01, LCL-02, LCL-03, LCL-04, LCL-05, LCL-06, LCL-07, DRI-01, DRI-03, DRI-04, ENV-01 (một số vị trí mã để trống trong tài liệu gốc).
- **Đã triển khai, cần kiểm tra lại: 11 yêu cầu** — DIS-06, DIS-07, DIS-08, DRI-02, REP-01, REP-02 (một số vị trí mã để trống trong tài liệu gốc).
- **Còn mở — chờ chốt: 2 yêu cầu** (mã để trống trong tài liệu gốc).
- **Tổng: 35 yêu cầu** — CUS 11 + DIS 10 + LCL 7 + DRI 4 + REP 2 + ENV 1.

*(DIS-08 tách riêng vì đang giữ trên môi trường thử nghiệm chờ nghiệm thu; các yêu cầu ghi còn mở chi tiết ở §7.1.)*

**B. ..23:**

- **Đã triển khai: 13** — 04, 06, 07, 08, 11, 14, 15, 16, 17, 18, 19, 20 (một số vị trí mã để trống trong tài liệu gốc).
- **Đã triển khai, cần kiểm tra lại: 7** — 03, 05, 09, 10, 12, 13 (một số vị trí mã để trống trong tài liệu gốc).
- **Còn mở — chờ chốt: 1** (đối chiếu quyết định 26/10).
- **Đã hủy/thay thế: 2** (cả hai thay thế ngày 22/10).
- **Tổng: 23**.

**C. Điểm Còn mở — chưa chốt:** 5 mục gốc §7.1 + 5 điểm bổ sung (ma trận thứ tự nhập liệu; xóa lô ĐV chờ áp dụng; nhóm chấm công thiếu bằng chứng; tạo khung giá qua giao diện; đối chiếu quyết định 26/10 vs /22) = **10 điểm đang mở**.

**D. Nghiệm thu:** 222 phiếu kết quả (219 đạt, 3 phiếu nợ kiểm thử hoàn thành ngày 21/10).

## Sơ đồ nhóm yêu cầu theo phân hệ

```mermaid
graph TD
    REQ["Tất cả yêu cầu nghiệp vụ"] --> CUS["Chứng từ & lô hàng"]
    REQ --> DD["Điều phối & lái xe"]
    REQ --> CUOC["Cước phí & báo giá"]
    REQ --> KT["Kế toán"]
    REQ --> QL["Quản trị & cấu hình"]
    CUS --> KQ["Đã chốt — đưa vào spec chi tiết"]
    DD --> KQ
    CUOC --> KQ
    KT --> KQ
    QL --> MO["Còn mở — chưa chốt"]
```
