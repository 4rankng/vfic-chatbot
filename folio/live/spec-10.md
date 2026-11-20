# 10. Yêu cầu giao diện người dùng (UI/UX)

Chương này gom toàn bộ yêu cầu giao diện: nút, hộp thoại, cột bảng, tab, nhãn, layout, bộ lọc, phím tắt, màu. Quy tắc nghiệp vụ, công thức, điều kiện trạng thái vẫn nằm ở chương nghiệp vụ gốc; mỗi ghi chú ghi rõ nguồn bằng số hiệu mục gốc (2.x / 4.x / 3.x / 5.x). Tiêu chí nghiệm thu chung ở 10.9; danh sách lỗi và yêu cầu còn mở ở 10.10.

Quy ước chung: thiếu dữ liệu hiện `—`, không hiện 0; tiền định dạng `1,000,000` toàn phân hệ (theo 5.7.4).

---

## 10.1 Màn hình danh sách lô hàng

Nguồn: 3.1.5, 3.1.7 và các mockup màn CUS.

### 10.1.1 Bố cục trang

- Thanh thẻ hai vị trí: thẻ hoạt động **"Tất cả lô hàng"** chứa toàn bộ bộ lọc và bảng làm việc; thẻ **"Hóa đơn kết hợp"** đặt trạng thái ẩn/chưa bật, chỉ dựng sẵn vị trí.
- Lưới **phẳng**: mỗi lô một dòng, không dòng xổ; bấm dòng lô mở **ngăn trượt (drawer)** dùng chung form tạo lô.
- Bản mẫu thứ hai là bảng hai lớp, dòng chi tiết xổ xuống ngay dưới dòng tổng hợp. Hai bố cục chưa loại được bên nào dứt khoát — *Chưa chốt: bản nào làm chuẩn, cần chủ dự án xác nhận.*
- Bộ lọc trạng thái theo mockup là `Mới tạo · Đang chạy · Chờ khóa · Đã khóa`, khác bảng trạng thái vận hành hiện hành và khác nhóm chip `Chưa chốt lịch / Chờ điều xe / Chờ đối soát` — *Chưa chốt: dùng bộ nào làm chuẩn, cần một bảng trạng thái duy nhất trước khi làm bộ lọc.*

### 10.1.2 Tìm kiếm và bộ lọc

- Ô tìm kiếm cho phép nhập **4–5 số cuối** của Số Bill/Booking hoặc Số tờ khai; phím tắt `/`.
- Bộ lọc ngày vận chuyển `Từ ngày – Đến ngày`; ở Tổng quan/Chi tiết dùng `transportDateFrom/To`, ở màn danh sách dùng `dateFrom/dateTo` (theo 3.1.5).
- Bộ lọc Nhập / Xuất / Tất cả; bộ lọc trạng thái lô; khách hàng (màn chi tiết container).
- Mặc định mở màn chi tiết container: lọc ngày vận chuyển = hôm nay đến hôm nay (theo mockup).
- *Đang mở:* lọc ngày trả sai ngày; ô tìm trên màn danh sách **công việc** tìm Bill/Booking trả 0 kết quả (theo 3.1.5).

### 10.1.3 Cột bảng tổng hợp (Lớp 1)

- Khách hàng · Nhà máy (điểm đóng/trả) · Số Bill/Booking · Số tờ khai · Hãng tàu · Tuyến đường · Nhập/Xuất · Kết hợp · Số lượng cont + loại (`2x40HC + 3x20HC`) · Kg tổng · CBM tổng · Ngày vận chuyển · Ghi chú.
- **Cột CHỨNG TỪ** hiển thị **tất cả số tờ khai của lô**, nối bằng `, ` (theo 3.1.7).
- **Cột "Tổng thu Khách (Không Hóa đơn)"**: hiện với vai CUS, ẩn với vai Ops.
- **Cột Trạng thái phơi phiếu**: danh sách 3 trạng thái `Ops đang giữ · Đã nộp Kế toán · Đã gửi Khách`.
- **Cột Kế toán duyệt**: hiện `Đã xác nhận: [ngày/giờ]` hoặc nhãn `Chờ xác nhận`. Thuật ngữ 3 trạng thái phơi phiếu cần đối chiếu với trạng thái phơi phiếu hiện hành của kế toán trước khi áp — *Chưa chốt.*
- Badge **NHẬP LẺ / XUẤT LẺ** trên dòng theo hình thức hàng và cấp lô (theo 3.7.4).
- Lô chưa có ngày đóng/trả: bôi nền cam nhạt toàn dòng (theo mockup). Container tới ngày vận chuyển mà chưa có xe: chữ đỏ tại khu vực nhà xe/biển số, có xe thì chữ đen bình thường (theo mockup; chưa có trong spec hiện hành, ghi nhận ở 10.10).

### 10.1.4 Bảng chi tiết theo container (Lớp 2)

- Cột: STT · Số container · Nhà xe (chọn từ danh mục **hoặc** nhập mới) · Biển số xe (nhập text) · Loại cont · Nâng · Hạ · Giờ đóng/trả.
- Ba nhóm cột cước, mỗi cột thành phần kèm cột **Số hóa đơn**:
  - **Cước đầu ra** — Phí vận chuyển · Phí làm hàng · Phí làm hàng · Tổng cước (tổng ba thành phần);
  - **Cước đầu vào** — cấu trúc giống cước đầu ra;
  - **Phí chi hộ** — CSHT · Nâng · Hạ · Khác.
- Ô cước dùng chung 2 dòng: **dòng trên số tiền, dòng dưới số hóa đơn** (theo yêu cầu demo).
- Cột Trạng thái phơi phiếu và Kế toán duyệt hiển thị ở Lớp 1 như 10.1.3.

### 10.1.5 Thao tác

- **[Khóa Lô]**: chỉ bật khi cột "Kế toán duyệt" đã có timestamp; bấm → lô chuyển "Đã khóa", toàn bộ ô nhập ở Lớp 1 và Lớp 2 chuyển chỉ-đọc.
- **[Đề nghị điều chỉnh]**: tự thay thế nút [Khóa Lô] khi lô đã khóa; mở popup có ô nhập lý do, gửi yêu cầu mở khóa. Luồng người duyệt (Admin) chưa có trong spec — *Chưa chốt.*
- **[TẠO LÔ MỚI]**: màu nổi bật, góc phải thanh công cụ; bấm → form tạo lô.

---

## 10.2 Tạo / sửa lô hàng

Nguồn: 3.2.1, 3.2.2, 3.2.3, 3.2.6, 3.4.3, 3.4.4, 3.7.1, 3.7.3 và 2.2.1, 2.2.3.

### 10.2.1 Bố cục form — band phẳng, thứ tự chốt

| Band | Nội dung |
|---|---|
| 1 | Khách hàng · Hình thức xuất nhập khẩu |
| 2 | Số Bill/Booking · Hãng tàu (chỉ hiện với FCL) |
| 3 (full width) | Tuỳ chọn — Lệnh chạy ngoài · Có cược container · Đóng kết hợp |
| 4 (cuối) | Số tờ khai — **đã gỡ ô nhập theo quyết định ngày 26/10/2026, xem 3.4** |

- Thứ tự band này là bản chốt; không đảo thứ tự nếu không có quyết định mới.
- Mockup đề xuất form 4 khối với render động FCL/LCL theo Loại hàng: tinh thần khớp, nhưng **thứ tự trường phải theo band trên**.
- Ô Bill/Booking bị tắt tới khi chọn Hình thức XNK; hint khi chưa chọn hướng: `"Chọn Hình thức xuất nhập khẩu trước"`; placeholder của ô bị tắt nói về chính ô đó (`"Nhập số Bill/Booking"`).
- Cổng Bill/Booking: sau khi chọn hình thức thì ghi số Bill (chiều Nhập khẩu) **hoặc** số Booking (chiều Xuất khẩu), không bao giờ cả hai (theo 2.2.1).
- Ô Tuyến khóa ghi nhãn `"Theo nhà máy"`; đổi khách hàng → chỉ rõ trường cần chọn lại.
- **Hàng lẻ**: nhãn động theo chiều — Nhập khẩu → ô Nhà máy `"Nhà máy (Điểm trả hàng) *"`, ô Kho `"Kho lấy hàng (CFS/Cảng) *"`; Xuất khẩu → `"Nhà máy (Điểm lấy hàng) *"`, `"Kho trả hàng (CFS/Cảng) *"`; cả hai ô là combobox (danh mục **hoặc** gõ text tự do) kèm `+ Thêm kho` / `+ Thêm nhà máy`; ô Kho nằm trong khu `"Điểm vận hành & tuyến"`.
- **Lệnh chạy ngoài** mặc định tắt; bật/tắt không mất nội dung đang nhập; có nhãn **Chạy ngoài** và bộ lọc riêng cho nhóm lô này (theo 2.2.3).
- **Số tờ khai**: chỉ nhập/sửa ở cấp container; **không** có ô nhập tờ khai cấp lô ở form và mọi điểm nhập theo lô (quyết định ngày 26/10).
- Nút/icon **[Chi tiết]** cạnh ô chọn Nhà máy: hover/click hiện popup thông tin nhà máy (Địa chỉ, MST…) (theo mockup).

- Thứ tự mục dưới Nhận diện lô: **Thông tin hàng**, sau đó **Ghi chú** (cho khách hàng, cho lái xe) ở dưới cùng; **không còn mục Lịch riêng** ở giữa (quyết định 30/10/2026).

### 10.2.2 Chip "Bắt buộc" và panel "Cần bổ sung"

- Chip hiển thị `"Bắt buộc: x/y"` với mẫu số duy nhất, dùng chung với panel **"Cần bổ sung N thông tin"**; tính bằng số trường bắt buộc đã hoàn thành cộng số lỗi còn lại (theo 2.2.1, 3.2.2).
- Panel phải hiện **trước khi** bấm "Tạo lô hàng". *Chưa chốt:* yêu cầu ngày 18/10 muốn ẩn panel khi mở trang và hiện sau bấm, mâu thuẫn với quy tắc trên.

### 10.2.3 Bảng thông tin hàng (dòng container)

- Mỗi dòng = 1 container: **Số · Loại · Trọng lượng · Thể tích (CBM) · Tuyến · Cảng nâng · Cảng hạ · Nhà máy · Ngày giờ đóng/trả**.
- Nút **`+ THÊM CONT`** thêm dòng mới; nút xóa từng dòng.
- Ngày đóng/trả là **theo từng container** (khác ngày cho từng cont của cùng lô); số container để trống được (theo mockup).
- **CUS-01**: nhập đủ 2 chữ số giờ (`'08'`) → tự nhảy ô phút (`'00'`).
- **CUS-03**: nút **"Copy thời gian"** gán ngày giờ chung cho mọi cont; nút Copy ở dòng mới copy cả dòng đó.
- **CUS-04**: TAB sang "Loại cont" rồi gõ phải tự mở gợi ý. *Đang mở:* gõ đè từng trả về label cũ.
- Chủ đề UX ngày 26/10: bảng dữ liệu dày, cột Số tờ khai vừa 11 ký tự; giữ mẫu số "Bắt buộc: x/9" + **thanh chân trang dính Huỷ / Lưu nháp / Tạo lô hàng**.
- **Ghi chú Điều xe** và **Ghi chú Thu khách** là hai textarea riêng trên form (theo mockup); map vào field nào trong spec — *Chưa chốt.*
- Mockup không đưa Nhà xe, Biển số xe, Chi phí, Trạng thái đổi lệnh vào form khởi tạo — khớp phân quyền hiện hành.
- Bố cục data-dense của bảng này đã chốt và triển khai 28/10: desktop gộp tối đa 3 dòng/ô (Số cont·Loại·Trọng lượng | Tuyến·Cảng | Ngày giờ đóng/trả), mobile (<768px) mỗi container một thẻ nhãn-trái/giá trị-phải.

### 10.2.4 Validate và thao tác quanh form

- Mọi trường bắt buộc trống phải **viền đỏ khi submit**; lỗi nằm cạnh trường cần sửa (theo 3.2.6).
- Cụm **Huỷ / Lưu nháp / Tạo lô hàng** ở đầu **vài cuối trang** (nhãn `… (cuối trang)`, aria-label riêng).
- Sau tạo FCL → tự chuyển sang Chi tiết lô; có nút **"Tạo lô mới"** cạnh "Xoá lô".
- **"Sửa lô"** = form Tạo lô ở chế độ sửa, route `/shipments/:id/edit`, tự điền dữ liệu đã lưu rồi ghi lại; hiển thị đúng ở 390/768/1440, không bị cắt.
- Ô tìm kiếm không tự biến chữ người dùng gõ thành lựa chọn đã chọn; chỉ pick của người dùng được chấp nhận (theo 2.2.1).
- Cảnh báo trước khi mất nội dung đang nhập khi đổi khách hàng (theo 2.2.1).
- *Đang mở:* tạo lô từ giao diện báo lỗi **400 `declarationNumber`**, chặn luồng (theo 3.2.6).

### 10.2.5 Sửa tờ khai và quản lý container

- Nhập/sửa số tờ khai **click ngay trên ô** trong bảng container (Chi tiết lô + Tổng quan); **bỏ nút Sửa riêng** (quyết định ngày 24/10).
- **Cột Số tờ khai** ở tất cả bảng liệt kê container theo từng dòng, click để sửa trực tiếp.
- **Lô khóa kế toán**: nút sửa tờ khai vẫn hiện nhưng bị tắt kèm lý do `"Lô hàng đã khóa kế toán; không thể sửa tờ khai."` (theo 2.6.2).
- **Hộp thoại "Quản lý container"** mở từ ô Tổng quan hàng hóa trên danh sách (đường chuẩn từ ngày 22/09); trên Chi tiết lô, thêm/bớt container hiển thị trực tiếp, điều kiện hiển thị/chấp nhận theo 3.7.1.
- Nút **"Xóa cont"** (CUS-10) trên bảng Chi tiết lô và ngăn trượt; container có chứng từ → chặn kèm đúng lý do; container đã có chuyến → chặn kèm lý do ngay hộp thoại (theo 2.6.3).
- *Đang mở:* hộp thoại `"Xóa container 2?"` bấm xóa không báo thành công, dữ liệu không đổi (theo 3.7.3).

### 10.2.6 Màn tiếp nhận yêu cầu (Bước 1)

- Thứ tự trường "Nhận diện lô" (chốt, đổi bố cục cần Trưởng bộ phận Điều vận chấp thuận): **Band 1** Khách hàng · Hình thức xuất nhập khẩu; **Band 2** Số Bill/Booking · Hãng tàu (chỉ với FCL); **Band 3** tuỳ chọn full width; **Band 4** Số tờ khai (chip, dán nhiều số — nay đã gỡ theo quyết định 26/10, xem 10.2.1).
- Nhãn bắt buộc: chip `"Bắt buộc: x/y"` dùng chung mẫu số với bảng "Cần bổ sung N thông tin".
- Lô lẻ hiển thị tag **NHẬP LẺ / XUẤT LẺ** ngay trên dòng.

---

## 10.3 Điều phối — Kế hoạch Tổng quát & Chi tiết Xe

Nguồn: 4.1.1, 4.1.2, 4.1.3, 4.1.7, 4.1.8, 3.6.1, 3.6.2, 3.6.3, 2.2.4, 2.6.3 và mockup Dispatch.

### 10.3.1 Tên màn hình

- Tên chính thức: **Kế hoạch Tổng quát** (`/dispatch`) và **Kế hoạch Chi tiết Xe** (`/dispatch-detail`). Tên "Lưới Điều Hành" không dùng (theo 4.1.1).

### 10.3.2 Kế hoạch Tổng quát

- Mỗi lô một dòng tổng hợp, trải phẳng ở cấp lô (theo 2.2.4, mockup).
- **Điều kiện hiển thị**: chỉ lô ở trạng thái "Sẵn sàng điều xe"; lô "Chờ chốt lịch" không xuất hiện ở đây (theo mockup; thành ràng buộc API — ghi nhận ở 10.10).
- **Cột CHỌN LÔ**: mặc định ẩn; hiện khi bật nút gộp hàng; tiêu đề thống nhất "CHỌN LÔ".
- **CẢNG NÂNG/HẠ** dòng lẻ = Kho lấy hàng / Điểm trả hàng do CUS nhập; không có → `—`; không ghi "Chưa có cont" (theo 4.1.2).
- **TỔNG QUAN HÀNG HÓA**: `[SL] [Loại bao bì] · [kg] · [CBM]` (vd `5 PALLET · 1.922 kg · 4 CBM`); ẩn CBM khi không có; bỏ "Chưa có cont".
- **PHÂN LOẠI / chiều**: badge NHẬP LẺ / XUẤT LẺ cho lô LCL; nhãn `Lẻ · Ghép (k/N)`.
- **Phân xe**: chưa gán → 1 nhãn mờ `"Chưa phân xe"`; dòng trống hiện `"Không có hàng lẻ chạy ngày đã chọn"`.
- **Thanh thao tác**: trạng thái "Chờ / Đang / Đã phân xe", "Chưa / Đã gán biển" (DIS-04); tìm Bill/Booking phải ra kết quả; chọn dòng lô mở đúng dòng ở Chi tiết Xe.
- **Cột PHÂN BỔ NHÀ XE** (cột thao tác duy nhất của điều vận trên màn này): bấm mở cửa sổ **"Phân bổ phương tiện"** — repeater mỗi dòng gồm chọn nhà xe · số lượng container · loại container, thêm/xóa dòng được (vd lô 4 cont chia 2 nhà xe: SS 2×40HC và HÀ AN 2×40HC); **tổng phân bổ vượt tổng số lượng của lô thì báo lỗi, không cho lưu**; sau lưu, cột hiển thị thẻ tổng hợp từng nhà xe (`SS: 2×40HC`, `HÀ AN: 2×40HC`). Cửa sổ này **độc lập** với cửa sổ "Gán xe nhóm" dùng cho gộp hàng LCL — không thay thế, không ghi nhóm chi phí.
- *Chưa chốt:* bản mẫu thể hiện cột phân bổ nhà xe là cột thao tác duy nhất, không có cột chọn lô, trong khi thiết kế gộp hàng ngày 23/10 đã đặt cột chọn lô — cần chủ dự án xác nhận.
- *Đang mở:* tìm Bill/Booking trả "0 lô" (theo 4.1.2).
- Mobile: giao diện data-dense, không lãng phí chỗ; thanh thao tác 44–48px.

### 10.3.3 Kế hoạch Chi tiết Xe

- Một dòng/container hoặc công việc; cột: nhà vận tải · biển số · tài xế · moóc · lịch · khách hàng/nhà máy · tuyến · cảng nâng/hạ · tình trạng nhận lệnh · ghi chú. Bản thu gọn cho mobile/tablet (theo 2.2.4, 4.1.3).
- **Cấm truncate**: mọi ô wrap full; header 2 dòng bị đè ("THỜI GIAN &/LỊCH TRÌNH") phải tách; "Ngày giao 23/10/2026" không đè "Trả hàng".
- Cột **ĐIỀU PHỐI** tách 5 dòng: nhà xe · biển số · tài xế · SĐT · trạng thái — không chi tiết nào bị ẩn/cắt.
- Dòng chưa phân nhà xe: bỏ dòng italic "CUS sẽ bổ sung", để trống.
- Cột **PHÂN LOẠI**: tag compact, 1 nhãn/dòng, header 1 dòng; pill `Lẻ · Ghép (n/2)` không tràn sang cột kế.
- Cột **SỐ TỜ KHAI**: sửa trực tiếp khi bấm vào ô, không cần nút Sửa.
- Cột **THAO TÁC**: xếp dọc (gửi trên, `⋯` dưới), "Hoàn thành" vào menu `⋯`, ~44–48px — còn mâu thuẫn với quy cách ~144px → *Chưa chốt: thống nhất một lần.*
- Số container in đậm, tên cảng chữ thường (DIS-08); trọng lượng hiển thị theo tấn, ô nhập vẫn kg (CUS-08); ô Ghi chú gõ được Space.
- Cột CONTAINER dòng LCL = `Lẻ · Xe 5T` / `5 PALLET` / `1.922 kg · 4 CBM`.
- **Hộp thoại "Chỉnh sửa điều phối"**: dùng hết bề rộng, không cuộn dọc; "Phát lệnh cho tài xế" + chân hộp thoại `Hủy / Lưu thay đổi / Phát lệnh` không bị cắt; chỉ giữ **một** trường ngày giờ duy nhất (quyết định 30/10/2026 — thay thế quy định cũ 'đủ Giờ điều vận + Giờ trả hàng'); *Chưa chốt:* gộp Phân loại + Cước thu dự kiến cùng hàng.
- **Tìm kiếm nâng cao**: bên cạnh tìm kiếm, lọc ngày, lọc nhập/xuất — lọc đa chọn điểm nâng · điểm hạ · điểm trả (nhiều điểm cùng trục đường để gom/ghép chuyến) và lọc khung giờ cao `Từ giờ – Đến giờ`.
- Biển số xe nhà xe ngoài: điều vận để trống ô biển số, CUS cập nhật bổ sung; **không** dùng dòng chữ giải thích trên bảng cho trường hợp này (theo 4.1.3).
- *Đang mở:* Kế hoạch Chi tiết Xe chưa có bộ lọc Loại hàng → toàn bộ lô LCL nằm ngoài trang 1, không tiếp cận được gộp hàng (theo 3.6.1). *Chưa chốt:* thêm bộ lọc / đổi thứ tự / hiện lý do nút bị tắt.

### 10.3.4 Phát lệnh

- Bấm tại dòng kế hoạch → chạy ngay theo dữ liệu đã lưu; không hẹn ngày/giờ, không hộp xác nhận lặp (theo 2.2.4).
- Nút hiện tiến độ, **không nhận bấm lần thứ hai**; lỗi hiển thị ngay tại dòng kế hoạch.
- **"Phát lệnh cho tài xế"** là hộp thoại của vai Điều vận.
- Lái xe chỉ thấy lệnh trên tab "Lệnh mới" sau khi phát lệnh.
- Người khác sửa phân công lúc đang mở màn → giữ nội dung đang nhập, không ghi đè ngầm (theo 4.1.8).
- **Xung đột lịch**: cảnh báo + hộp xác nhận `"Vẫn lưu?"` ở tầng bằng chứng yếu (chỉ có ngày); hai dấu thời gian mạnh → chặn cứng, không hộp thoại (theo 2.2.4).

### 10.3.5 Gán xe nhóm, đổi nhà xe, xóa lô

- **Đổi nhà xe/biển số**: menu dòng → hộp thoại **"Đòn nhà xe/BKS"**; nhà xe ngoài chưa biển số thì kèm chip chờ biển (DIS-09) và hộp xác nhận `"Vẫn phát lệnh?"` (theo 2.2.4).
- **Cửa sổ "Gán xe nhóm" — 4 trường** (quyết định 23/10, đã bỏ biển số ảo khỏi màn ĐV): Loại xe tính cước trả ĐV (tấn 1.25T–15T hoặc Cont 20'/40'; xe tải → chỉ nhà xe ngoài, cont → nội bộ hoặc ngoài) · Nhà xe (từ danh mục khách hàng đánh dấu là nhà xe) · BKS thực (xe nội bộ bắt buộc chọn từ đội xe công ty) · Cước trả ĐVVC (đ) (trống = tra bảng giá, nhập tay = lấy giá nhập). → ghi nhóm chi phí: Lô 1 = 100%, Lô 2..N = 0 ₫ (luật tiền theo 4.1.7).
- **Gom nhóm LCL**: hành động **Gán xe nhóm** trên Kế hoạch Chi tiết Xe; cảnh báo tải trọng chỉ cảnh báo, không chặn; hộp thoại chỉ nhận nhà thầu (xe ngoài) khi chọn "Xe tải", chặn nếu nhận xe nội bộ và chặn nếu nhà xe đã cũ (theo 2.2.4).
- Nút **"Xóa lô"** trên Kế hoạch Chi tiết Xe giữ lại cho CUS, Quản trị viên, Điều vận; Ops không có quyền; xóa container đang có chuyến bị chặn kèm lý do ngay hộp thoại (theo 2.6.3).

### 10.3.6 Gộp hàng (ĐV và CUS)

- Nút **`Gộp hàng`** (viền/secondary) trên thanh bộ lọc của Kế hoạch Tổng quát / Chi tiết Xe (ĐV) và Chi tiết lô / Chi phí–Quyết toán (CUS); **mặc định cột CHỌN ẩn**, bấm mới hiện hộp chọn (theo 3.6.3, 4.1.7).
- Hộp chọn chỉ hiển thị dòng LCL (dòng FCL bị làm mờ), gộp từ ≥2 lô; chọn ≥1 dòng → **thanh chọn nổi** `"Đang chọn N lô: Tổng X tấn | Y CBM — Lô 1 giữ 100%…"` + nút bật cửa sổ + Bỏ chọn/Hủy; thoát → tự ẩn cột + đóng thanh.
- **ĐV — popup gộp xe** (sau 23/10) 4 trường: Loại xe tính cước trả\* · Nhà xe\* · BKS thực\* · Cước trả ĐVVC (theo 3.6.2).
- **CUS — popup gộp hàng** per-lot 3 trường/lô: Loại xe thu · Giá cước thu · BKS báo khách (trống → lấy BKS thực). Ghép: loại xe thu chung · BKS ảo chung · cước Lô 1 (theo 3.6.2).
- Nút **[Tách nhóm] / [Hủy ghép]** ở Chi phí–Quyết toán và Kế toán chốt debit — chức năng hủy ghép đã có nhưng chưa gắn vào giao diện (theo 3.6.3).
- Nút dùng **biểu tượng vector**, không emoji `📦` — đã hoàn thành 27/10 (theo 4.1.7).

---

## 10.4 Ứng dụng lái xe

Nguồn: 4.2.1–4.2.9 và 2.2.5.

### 10.4.1 Điều hướng

- **4 tab: Hành trình · Thu nhập · Kỷ luật · Tài khoản**; Hành trình → **Lệnh mới · Đã nhận · Lịch sử**; số lượng/trạng thái theo tài khoản (theo 4.2.1).
- Ảnh/biên lai/chi phí thuộc đúng công việc, chỉ người có quyền thêm/sửa.

### 10.4.2 Thứ tự nội dung thẻ lệnh

- Thứ tự nội dung thẻ: ① nhận diện (nhãn **ĐƠN/ĐẸP/KẾT HỢP** + lịch đóng/trả đủ ngày giờ khi có) → ② tên ngắn nhà máy (thiếu thì tên đầy đủ) → ③ tuyến ngay dưới (không thay bằng địa chỉ) → ④ container: mỗi số cont kèm loại của chính nó (vd `EMCU6163403 · 20DC`) + nhãn TRẢ HÀNG/ĐÓNG HÀNG đúng công việc → ⑤ cảng nâng/hạ đúng chiều, đúng nguồn → ⑥ nhiệm vụ viết hoa dòng riêng, ghi chú lái xe dòng riêng → ⑦ thao tác đi kèm khớp trạng thái thực tế (không hứa nhiều thao tác nhưng chỉ làm được 1).
- **Chi tiết lệnh**: tiêu đề ưu tiên tên viết tắt nhà máy, tuyến ngay dưới; phần thông tin lệnh hiện địa chỉ nhà máy (không lặp tuyến).
- Thứ tự nhóm: Bill/Booking (định danh chính) → lịch & địa điểm (nhà máy → địa chỉ → người liên hệ + SĐT, bấm gọi được) → hàng hóa (số cont gắn loại, số chì, thao tác) → lộ trình (cảng nâng/hạ, điểm giao/điểm trả vỏ) → nhiệm vụ & ghi chú → xuất hóa đơn (tiêu đề từng bên trước tên/địa chỉ/MST) → bằng chứng & hành động.
- Tác vụ + ghi chú lái xe ngay sau thông tin công việc, trước hóa đơn; không thêm dòng đầu kéo/moóc; phần dài thu gọn độc lập.

### 10.4.3 Nhận lệnh

- Lệnh hợp lệ phát đúng tài xế → tab **Lệnh mới**; thông báo mở đúng công việc; trực tuyến → danh sách tự làm mới (theo 4.2.3).
- Xe/tài xế/moóc bận: lý do + liên kết công việc đang chặn hiển thị bền vững, kèm hướng dẫn từng bước làm — không chỉ nút "tải lại"; cặp Kẹp không bị coi là xung đột.
- Lái xe chủ động nhận lệnh tại tab Lệnh mới (theo 2.2.5).

### 10.4.4 Yêu cầu ảnh và e-POD

| Lớp | Yêu cầu | Ghi chú |
|---|---|---|
| Nhận lệnh | Không bắt buộc tải ảnh | |
| Hoàn thành — FCL | **Bắt buộc 2 nhóm bằng chứng đã lưu**: ① Phiếu hạ bãi/trả hàng ② Biên bản giao nhận (dấu/chữ ký) | |
| Hoàn thành — ảnh e-POD | **Tùy chọn**: hoàn thành với 0 ảnh được; nhãn "Tùy chọn / Chưa có" thay "bắt buộc" | Quyết định ngày 22/10/2026 |

- Ảnh tải 100% ≠ hồ sơ đã lưu: người dùng biết ảnh nào đã lưu/mở lại được.
- 1 ảnh thất bại sau ảnh đã lưu → giữ tiến độ từng ảnh, thử lại ảnh lỗi, không tạo bản sao; ảnh có dấu thời gian thực tế; xem ảnh phóng to, Esc đóng.

### 10.4.5 Thẻ Kẹp / Kết hợp

- **KẸP**: từng container 1 thẻ riêng (số cont, số chì, khối lượng) + nút sửa riêng; 2 thẻ liền kề có dấu hiệu cùng cặp, mỗi thẻ vẫn có container/loại/lịch/thao tác riêng.
- **KẾT HỢP**: trả Lệnh 1 xong mới đóng Lệnh 2; màn hình nêu lý do phần sau chưa bắt đầu.

### 10.4.6 Hoàn thành chuyến

- Bấm **Hoàn tất lệnh vận chuyển** → màn e-POD; FCL cần 2 nhóm bằng chứng (10.4.4).
- Đã Nhận lệnh + đủ 2 nhóm bằng chứng đã lưu → nút **HOÀN THÀNH CHUYẾN** gửi hồ sơ e-POD, hoàn thành 1 thao tác (theo 2.2.5, 4.2.6).
- Sau xác nhận thẻ → chuyển tab **Lịch sử**.
- **Chuyến xe ngoài**: giao diện hiển thị nguyên nhân do hệ thống trả về khi không tính được hạn mức thanh toán (theo 2.2.5).

### 10.4.7 Chi phí lái xe

- Hai bảng **"Chi phí lô hàng"** và **"Tiền đường"**; tiền đường lái xe chỉ nhìn, kế toán điều chỉnh; lái xe chọn loại chi phí và điền số, thêm liên tục không cần lưu từng dòng (theo 2.2.5). Chi tiết ở 10.6.

### 10.4.8 Mã chuyến và các khu còn lại

- **Mã chuyến không hiển thị ở đâu cả**: thẻ lệnh, tiêu đề chi tiết, banner lỗi; định danh chính là Số Bill/Booking (theo 4.2.7). *Đang mở:* còn một dòng hiển thị dạng "MÃ CHUYẾN …" — cần bỏ.
- Ba khu còn lại sau Hành trình: **Thu nhập · Kỷ luật · Tài khoản** — nội dung nghiệp vụ ở 4.2.9, phần hiển thị theo tab ứng với từng khu.

---

## 10.5 Danh mục & dữ liệu chủ

Nguồn: 4.3.3, 4.3.4.

### 10.5.1 Màn `#/config/factories`

- Quyết định ngày 24/10: **bỏ cột TRẠNG THÁI** (hàng ngừng hoạt động → mờ + tooltip "Đã ngưng"), gộp MÃ + TÊN (vd `NEWEB-3 · CÔNG TY TNHH NEWEB VIỆT NAM`, truncate ~260–320px + tooltip), Địa chỉ/Liên hệ 1 dòng `'địa chỉ • SĐT'` + biểu tượng gọi 20–24px, **bỏ STT**, LOẠI thành badge nhỏ hoặc cột ~80px, dòng 48–52px, header ~40px.
- Giữ filter/search/sort/count "15 mục"/Tạo mới/sửa-xóa; không đổi giao diện dữ liệu; không đổi API operational-site + contacts; card band mobile ≤1100px không vỡ; không cắt chữ.

### 10.5.2 Chọn nhà máy khi lập công việc

- Tìm/tải không mất lựa chọn mới nhất; tìm trong phạm vi KH theo mã/tên tắt/tên đầy đủ/địa chỉ, không phân biệt hoa/thường, có/không dấu; không có kết quả → "Không tìm thấy kết quả"; **nhập từ khóa không tự tạo nhà máy**; tuyến khóa ghi nhãn "Theo nhà máy" (theo 4.3.3).
- Tình huống: nhà máy cũ chưa có tuyến → chỉ rõ thiếu; KH chưa có nhà máy → giải thích danh sách rỗng; ngừng hoạt động/tải lỗi → phân biệt lỗi với rỗng, cho thử lại; người khác sửa lúc đang nhập → giữ nội dung, hiển thị thay đổi.

### 10.5.3 Ô chọn kho / nhà máy

- Ô chọn: chọn từ danh sách **hoặc** gõ tự do, kèm `+ Thêm kho/nhà máy`; nhãn động theo hình thức XNK (theo 4.3.4).
- SĐT kho/nhà máy hiện trên cửa sổ popup của điểm vận hành.
- **Tìm kho phải khớp đầy đủ**: gõ đủ "GLC" phải ra "GLC" (hoa/thường, có/không dấu, chuỗi con); lỗi thuộc cơ chế lọc của ô chọn, không phải thiếu dữ liệu chủ. *Đang mở:* ô chọn danh mục lọc sai khi tìm chuỗi con.

---

## 10.6 Cước phí, khai chi phí, bảng kê

Nguồn: 5.1.2, 5.1.6, 5.2.3, 5.3.2, 5.4.3, 5.5.2–5.5.5, 5.6.2–5.6.3, 5.7.4 và 2.2.7.

### 10.6.1 Kế hoạch điều động tổng hợp — nhóm cột tiền (5.1.2)

- Mỗi lô một dòng, tiền tách hai nhóm cột:
  - **PHẢI THU**: Cước thu auto · Lạch Huyện auto · Phụ phí auto · Phát sinh (CUS) · Tổng thu;
  - **PHẢI TRẢ**: Cước trả ĐV · Lạch Huyện (điều vận) · Phát sinh (điều vận) · Tổng 1 · Phí RU.
- Cột Cước thu dự kiến hiển thị chỉ-đọc (cước tự tính theo hợp đồng); giá đã phát hành nằm ở bảng kê, tách khỏi cột này; sửa lô không mở lại ô giá đã phát hành.
- Cột phụ phí vùng: hết nguồn hiện `—`, không bao giờ tự điền 0.
- Thiếu cước hiện ngay trên ô dòng: nhãn "Thiếu cước thu / Thiếu phụ phí…".

### 10.6.2 Màn khai chi phí của lái xe (5.1.6, theo 2.2.5)

- Hiện 2 bảng: **Chi phí lô hàng** + **Tiền đường**.
- Đã bỏ cột Người chi; đã bỏ Số hóa đơn & Ngày hóa đơn; thêm 2 ô **Hóa đơn / Phiếu thu**.
- Dòng Tiền đường chỉ-đọc với lái xe (hệ thống ghi nhận, kế toán điều chỉnh).
- Dòng Nâng/Hạ Lạch Huyện điền tự động, không có ô nhập tay.
- Dòng Loại chi phí: lái xe chọn từ danh mục + ô số tiền; thêm dòng liên tục được, không bấm lưu từng dòng.
- **Kiểm soát phơi phiếu → Thêm khoản chi**: nhóm chi phí chỉ hiện 2 nhóm Tiền đường / Chi phí lô hàng.
- Ô **Chụp / Chọn ảnh** là tùy chọn — không ảnh vẫn ghi được dòng chi phí (theo 5.4.3).

### 10.6.3 Khai chi phí bước 7 (2.2.7)

- Nhập trùng chi phí Ops → báo lỗi trùng lặp kèm bảng xác nhận chủ đích (2 nút); dòng đã hủy không cảnh báo.
- **Cược container**: tick "đã hoàn cược" = đã thu + chuyển tiền về quỹ công ty (ACB); mỗi dòng ghi đúng một bút toán, tick lại bị chặn.

### 10.6.4 Ô chứng từ trên màn khai chi phí (5.4.3)

- Ô đánh dấu (checkbox) = cờ có hóa đơn: bật lên mới hiện và yêu cầu số hóa đơn.
- Ô "Nhập thu/trả bằng nhau": bật = 2 ô số tiền liên động; tắt = 2 ô sửa độc lập.
- Ô Nhà cung cấp điền sẵn tên nhà xe chạy tuyến đó, sửa được.

### 10.6.5 Báo giá (5.2.3, 5.6.2–5.6.3)

- Lưới giá trong khung Báo giá: mỗi ô hiển thị 3 giá trị — hệ số · tổng lít/chuyến · giá cos; cột/hàng theo `Nhà máy × Tuyến đường × Hạng phương tiện`; phụ phí hiển thị đã làm tròn ROUND Excel, giá cos không làm tròn.
- Khung báo giá: các ô tên mẫu, giá dầu tham chiếu, lag, quy tắc làm tròn phụ phí, ngày hiệu lực, chế độ làm tròn theo khách; có chọn phiên bản, bản cũ mở được chỉ-đọc.
- Ô nhận diện khách bắt buộc cả tên đầy đủ + mã số thuế; lệch nhà máy/tuyến → báo lỗi từng dòng.
- Xuất Excel: khớp mẫu, cột lít không thập phân; cửa sổ chọn phiên bản mặc định gồm cả hôm nay; lọc mặc định chỉ hiện bản mới nhất mỗi khách.

### 10.6.6 Tính cước khi lập/bổ sung lô (5.3.2)

- Đủ đầu vào: ô cước hiện số đã khóa kèm dòng nguồn "cách tính và nguồn" (kèm giá gốc/kỳ giá dùng).
- Thiếu đầu vào: thông báo ghi rõ thiếu ở giá gốc / ngày / lag / ngưỡng / kỳ giá; ô cước không hiện 0.
- Màn nhập kỳ giá dầu: 3 ô giá · ngày hiệu lực · nguồn; lỗi validation báo ngay tại trường cần sửa, giữ nguyên nội dung đã gõ.

### 10.6.7 Tờ khai hải quan (5.5.2)

- Mục "Tờ khai hải quan" có nút **"+ Thêm tờ khai"** và thao tác xóa dòng.
- Trường sửa được với quyền Quản trị / CUS / Quản lý / Điều vận (quyết định chủ dự án 29/10/2026: số tờ khai là dữ liệu vận hành hàng ngày của điều vận); lô khóa kế toán → trường hiển thị khóa kèm lý do.
- Trùng số tờ khai → báo lỗi trùng số tại ô.
- Trạng thái "thiếu thông tin": có tờ khai (cấp cont hoặc cấp lô) = ĐẦY ĐỦ; không có = VẪN THIẾU.
- Trường "Luồng hải quan" (đỏ/vàng/xanh) đã bị gỡ khỏi màn hình lẫn dữ liệu (từ 02/10) — không còn hiển thị.

### 10.6.8 Định danh lô/vận đơn (5.5.3)

- Khóa hiển thị ưu tiên: Số Bill/Số Booking → số tờ khai → tên khách + ngày chi; vắng hết hiện `—`.
- Mã vận đơn nội bộ (`SHP-*`, `TRP-*`, số #) không xuất hiện trên mọi màn hiển thị định danh.

### 10.6.9 Hộp thoại Xuất Debit & Bảng kê (5.5.4)

- Luồng thao tác: lọc theo nhà xe → tích ALL/dòng → hộp thoại.
- Hộp thoại: **Từ ngày–Đến ngày · Lần · Tháng · Phải thu/phải trả** → danh sách tên + số tiền; VAT chọn 0/5/8/10%, tổng = tiền + VAT hiển thị cộng dồn.
- Trên Debit/Bảng kê gửi khách: cột BKS in từ **BKS báo khách**, không in BKS thực; cột Loại xe theo loại xe tính cước thu khách. Ở chiều PHẢI TRẢ: cột BKS in BKS thực + loại xe tính cước trả.
- Dòng thiếu dữ liệu hiện nhãn "Thiếu cước thu / Thiếu phụ phí…" thay vì số 0; dòng chờ điều chỉnh cước bị chặn ở bước xuất Debit (AC-KT-13).
- Chọn lô đã thuộc bảng kê khác → bị chặn kèm nêu số lô.

### 10.6.10 Màn gộp hàng / tách nhóm LCL (5.5.5)

- Nút Gộp hàng bật/tắt cột CHỌN (chỉ dòng LCL) — cột CHỌN chỉ hiện khi bật nút Gộp hàng và tự ẩn khi thoát.
- Dòng LCL hiển thị tag `Lẻ · Ghép (k/N)`; lý do 0đ/100% hiển thị trên dòng.

### 10.6.11 Hiển thị thiếu dữ liệu (5.7.4)

- Thiếu giá 15T: ô hiện `—` + nhãn "Thiếu giá 15T".
- Phân biệt 3 trạng thái trên mọi màn: "Chưa xác định" (nhãn) / `—` (chưa có giá trị) / `0` (đã tính, kết quả 0).
- Định dạng số dùng chung toàn ứng dụng; trọng lượng theo tấn.

---

## 10.7 Kế toán

Nguồn: 2.2.8, 2.2.9, 2.6.2 và 5.4.4.

### 10.7.1 Phơi phiếu (Bước 8, 2.2.8)

- Bảng tổng hợp với các cột: lịch trình · khách hàng · thông số container · địa điểm nâng/hạ · xe · **CHI HỘ** (3 cột tiền) · **TIỀN ĐƯỜNG** · ghi chú vận tải · ghi chú lái xe.
- Hai bảng: (1) Chi phí Ops & hoàn ứng; (2) Phơi phiếu & tiền đường.
- Phân công kế toán theo xe thể hiện qua **bộ lọc mặc định** (1 xe ↔ 1 người phụ trách hiện hành, 1 người ↔ nhiều xe), không thu hẹp quyền xem.

### 10.7.2 Popup Thêm khoản chi (5.4.4)

- Thứ tự trường: `Ngày · Nhóm chi phí · Tên khoản chi · Bên thực chi · Nhà cung cấp · Số hóa đơn – ngày hóa đơn (điền hoặc không) · Nhập thu/trả bằng nhau`.
- Chọn "Bên thực chi" → hiện 3 mục chi phí.

### 10.7.3 Bảng duyệt tiền đường (5.4.4)

- Cột Tích duyệt / Từ chối; dòng **ĐÃ DUYỆT** mới đi vào phiếu chi trả lái xe; cột Tiền đường của bảng kiểm soát phơi phiếu hiển thị trạng thái đã duyệt.

### 10.7.4 Màn chốt debit (Bước 9, 2.2.9)

- Bảng theo lô với **cột thu** (cước thu tự động, Lạch Huyện, phụ phí, phát sinh bên thu) và **cột trả** (cước trả điều vận, Lạch Huyện điều vận, phát sinh điều vận, tổng 1, phí RU bên trả).
- **Popup Chọn Debit** là hành động chốt (không phải bộ lọc): lần 1,2,3…, tháng, chiều thu/trả, **VAT 0/5/8/10%** (tiền VAT + tổng tự tính), ghi chú.
- **"Duyệt" ở đây = đối soát**: tick dòng → gửi yêu cầu điều chỉnh cước; đang chờ → lô không xuất được debit (hệ thống nêu rõ mã lô); xác nhận từng dòng hoặc tick tất cả để mở khóa.
- Tick **"Bỏ xe công ty"** do hệ thống tính lại; bản xuất dùng đúng bộ lọc đang bật; tick không ẩn khách nào.
- Sau chốt: bảng **TỔNG HỢP CÔNG NỢ KHÁC HÀNG** tự liệt kê các đợt đã chốt (kỳ = lần + tháng).

### 10.7.5 Màn hình sau khi đã chốt (2.6.2)

- Tờ khai trên lô khóa: nút hiện nhưng bị tắt kèm lý do ("Lô hàng đã khóa kế toán; không thể sửa tờ khai.").
- Khoản chi đã có số hóa đơn: khóa trên màn quyết toán; muốn đổi thì sửa tại nguồn chi phí.
- Đợt hoàn tác: không còn nút trả/thu tiền trên đợt đã hoàn tác.

---

## 10.8 Hiển thị chung toàn hệ thống

Nguồn: 2.3.2, 2.3.3, 2.4.4, 2.4.9, 2.5.1, 2.6.1, 2.6.4, 2.6.5, 4.4.2, 4.4.3 và đặc điểm chung của các mockup.

### 10.8.1 Phím `←` / `→` cuộn ngang (4.4.2)

- **Toàn cục**: `←` `→` cuộn ngang cho **mọi bảng trong ứng dụng**, không chỉ `/dispatch-detail`.
- Kết hợp **cấm truncate** — mọi ô wrap full; cột tự giãn, bảng không cắt cụt; mã/BKS/SĐT giữ nguyên cụm.
- Bảng dày đặc trên mobile vẫn đủ chiều rộng + cuộn được, nút dễ chạm, không chồng.

### 10.8.2 Nguyên tắc data-dense (4.4.3)

- Mục tiêu chủ sản phẩm: giao diện **elegant, data-dense, không lãng phí chỗ** — Kế hoạch Tổng quát mobile, form Tạo lô hàng, trang danh mục.
- Chỉ số đã chốt: dòng 40–52px, header 36–40px; hộp thoại dùng hết bề rộng, không cuộn dọc; toolbar 44–48px; thẻ lái xe "Chứng từ giao hàng" ≤60px.
- Gộp trường/cột cùng hàng khi chỗ còn trống: Phân loại + Cước thu dự kiến; MÃ + TÊN; LOẠI + TRỌNG LƯỢNG vào cột SỐ CONTAINER.
- Không mất thông tin để dày thêm: ẩn cột chỉ khi toàn giá trị rỗng, tự hiển thị lại khi có dữ liệu; bỏ dòng phụ không dữ liệu; "Chưa phân xe" 1 dòng.
- Các mockup dùng mô hình **gộp nhiều dòng/cell (tối đa 3 dòng) vào 1 ô** để triệt tiêu thanh cuộn ngang — cùng hướng với quy tắc trên. Bố cục đã chốt và triển khai: bảng Thông tin hàng desktop gộp 3 dòng/ô; mobile (<768px) mỗi container một thẻ; Kế hoạch Tổng quát trên 768px hiển thị master-plan không vỡ dòng.

### 10.8.3 Màu sắc (4.4.3)

- **Sage `#E3E8E5` là thiết kế chính thức** (token nền), thẻ/bề mặt giữ trắng để nổi trên nền — thay yêu cầu nền trắng trước đó.
- Một kiểu thanh lọc dùng chung; header bảng **1 dòng**.
- Bảng màu hiệu chuẩn: chữ tương phản ≥ 4,5:1; xanh "thành công" chỉ cho hoàn thành/đã thu; **tiền chưa thu = vàng cảnh báo** (theo 1.5.8).
- Không phân biệt trạng thái chỉ bằng màu hoặc hover (theo 1.5.5).

### 10.8.4 Thao tác nhập và hiển thị (2.4.9)

- Nút **Xác nhận** rõ; gõ/chọn/Enter cho cùng kết quả; chỉ báo đã lưu khi mở lại còn đúng; xóa lịch → về "chưa chốt lịch", không tự điền hôm nay.

- Ô ngày giờ toàn app: **NGÀY trước, GIỜ sau — DD/MM/YYYY HH:MM**, một luật thống nhất cho cả hiển thị và ô nhập (SplitDateTimeField: ô ngày trước, ô giờ sau; picker mở ngày trước giờ — quyết định 30/10/2026).

### 10.8.5 Phản hồi lỗi, phiên, dữ liệu (2.5.1, 2.6.1, 2.6.4)

- **V03**: viền đỏ tại đúng ô + thông báo gắn đúng trường.
- **V06**: lỗi hiện tại dòng kế hoạch.
- **V17**: bảng xác nhận 2 nút.
- **V32 — Responsive**: 390px / 820px / desktop; bộ lọc & trường tiền cùng cỡ, không tràn, không thẻ lồng thẻ, thao tác bàn phím được (AC-CP-KT-21).
- Lỗi kết nối tạm thời → giữ phiên + nút thử lại (không mô tả thành hết phiên đăng nhập nếu tài khoản còn hợp lệ).
- Cập nhật phiên: tab mở qua đợt cập nhật → báo có phiên bản mới, người dùng chọn thời điểm làm mới; không tự tải lại giữa chừng (mất nội dung đang nhập).

### 10.8.6 Trạng thái chung (2.3.2, 2.3.3, 2.4.4, 2.6.5)

- **Chờ điều xe**, **Chờ đối soát** là hai chip hiển thị trên Tổng quan lô CUS.
- Màn Ops theo dõi xe/máy **chỉ đọc**: không có nút xác nhận/sửa tiến độ; trạng thái "Dữ liệu chưa cập nhật" hiển thị thời điểm của thông tin đang xem.
- Bộ lọc chứng từ **không** đổi tổng tiền đường.
- Chuyến ngoài chốt: hiện mục riêng chỉ-read dưới Bảng 2.3 với nhãn **Ngoài chốt**; ẩn khi không có; màn chốt debit cũng loại + hiện dòng tổng tiền bị loại.
- Lô LCL ở Tổng quan nhưng mất ở Chi tiết: lỗi dữ liệu phải sửa, không chấp nhận trạng thái hai màn hình lệch nhau (LCL-01).
- "Số yêu cầu chờ duyệt" trên trang tổng quan Ops — *Chưa chốt:* mâu thuẫn với nguyên tắc không phê duyệt, cần xác định dữ liệu đếm.

---

## 10.9 Chuẩn chất lượng trải nghiệm

Bộ yêu cầu trải nghiệm gồm **7 nhóm** phải đạt. Đây là tiêu chí nghiệm thu chung, độc lập với từng màn hình.

### 10.9.1 Dễ nhận biết
Người dùng luôn biết **đang ở đâu**, lô/kỳ **nào**, **thiếu gì**, **bước sau** là gì; tên, ngày, tiền, trạng thái **thống nhất** giữa danh sách, màn chi tiết và chứng từ.

### 10.9.2 Ít nhập lại
Dữ liệu **kế thừa đúng nơi**; đổi một lựa chọn thì các trường phụ thuộc cập nhật theo; **không âm thầm mất** nội dung đang sửa.

### 10.9.3 Lưu đáng tin cậy
Bấm lưu **nhiều lần không tạo bản ghi trùng**; khi **người khác sửa cùng dữ liệu** thì hiển thị thay đổi và để người dùng **tự quyết cách tiếp tục**, không bị ghi đè.

### 10.9.4 Tận dụng diện tích
Bảng hỗ trợ **so sánh**; màn nhỏ ưu tiên **định danh, lịch, trạng thái, số liệu chính, hành động**; mã quan trọng (mã lô, số container, số Bill…) **không bị cắt/gãy ký tự**; nhóm trường dùng **khoảng cách + tiêu đề**, tránh nhiều lớp khung.

### 10.9.5 Thao tác thuận tiện
Thao tác **dễ chạm** và **dùng được bàn phím**; có **lỗi cạnh trường**; **nút Lưu/Đóng luôn tiếp cận được** kể cả khi bàn phím ảo điện thoại đang mở; **không phân biệt trạng thái chỉ bằng màu** hoặc hover.

### 10.9.6 Phản hồi rõ & ổn định
Phân biệt rạch ròi *đang tải* / *trống* / *lỗi tải* / *đang lưu* / *đã lưu*; tôn trọng cài đặt **giảm chuyển động**; cập nhật dữ liệu **không làm nhảy hàng** và **không làm mất nút đang dùng**.

### 10.9.7 Giữ ngữ cảnh
Quay lại danh sách **giữ bộ lọc, trang và vị trí**; **đổi tài khoản không để lại dữ liệu** của người trước; lỗi kết nối tạm **không đá phiên làm việc còn hợp lệ**.

### 10.9.8 Quy tắc hiển thị hợp nhất (bổ sung đang áp dụng)

Quyết định ngày 16/09–22/09/2026 hợp nhất quy tắc hiển thị: dữ liệu bảng **trọn vẹn, không cắt cụt** (mã/BKS/SĐT giữ nguyên cụm); **trạng thái dạng chữ**; **một kiểu thanh lọc dùng chung**; **màn trống thống nhất**; **lớp nổi** dùng chung nền; **bảng màu hiệu chuẩn** — chữ tương phản ≥ 4,5:1, xanh "thành công" chỉ cho hoàn thành/đã thu, **tiền chưa thu = vàng cảnh báo**; vi phạm phải được **kiểm tra tự động** ngay.

### 10.9.9 Xử lý tình huống bất thường
Sản phẩm phải đáp ứng **cả** luồng thường lẫn: **thiếu dữ liệu, nhập sai, mất kết nối, đổi đồng thời, tên/mã dài, nhiều bản ghi**.

### 10.9.10 Chuẩn mobile production grade (bổ sung 29/10)

Toàn ứng dụng áp chuẩn mobile khi bề rộng dưới 768px: mỗi dòng dữ liệu chuyển thành thẻ dọc đủ thông tin; chữ không cắt cụt; vùng chạm tối thiểu 44px; ô nhập từ 16px để tránh iOS tự phóng trang; tương phản chữ đạt AA; không xếp lớp thẻ chồng thẻ. Mục tiêu: mobile data-dense ở mức production grade — dày nhưng không chật, đầy đủ nhưng không rối.

---

## 10.10 Lỗi giao diện đang mở

Tổng hợp từ các file giao diện của 4 chương nghiệp vụ và phân tích 6 mockup. Không dùng mã vé nội bộ; lỗi ghi kèm nguồn số hiệu mục.

**Cập nhật 29/10**: mục 13 (Gộp hàng chưa triển khai) đã hoàn thành theo đợt 28/10; mục 15 (nhãn vỡ layout) đã sửa theo bố cục SIL-552; mục 19 (mobile data-dense) hoàn thành theo chuẩn mobile 29/10 (10.9.10). Các mục còn lại tiếp tục theo dõi.

### 10.10.1 Lỗi đang mở theo màn hình

**Danh sách lô hàng (3.1.5, 3.1.7)**
1. Ô tìm trên màn danh sách công việc tìm Bill/Booking trả 0 kết quả; lọc ngày trả sai ngày.
2. Bản mẫu danh sách lô hai bố cục khác nhau (2 lớp xổ xuống vs phẳng + drawer) chưa loại được bên nào.
3. Bộ lọc trạng thái `Mới tạo · Đang chạy · Chờ khóa · Đã khóa` khác bảng trạng thái hiện hành — taxonomy lệch, cần 1 bảng trạng thái duy nhất.

**Tạo/sửa lô (3.2.3, 3.2.6, 3.4.3, 3.7.3)**
4. Tạo lô từ giao diện báo lỗi **400 `declarationNumber`**, chặn toàn bộ luồng tạo lô — nghiêm trọng.
5. CUS-04: ô "Loại container" không tự mở gợi ý khi gõ đè; gõ đè từng trả về label cũ.
6. Cột CHỨNG TỪ trên danh sách chỉ hiện Bill + "Chưa có tờ khai"; nhập tờ khai không lưu/không hiện; thêm container mới không lan tờ khai; hàng LCL không nhập được tờ khai và không phân xe được (ô thao tác không hoạt động, FCL bình thường).
7. Danh mục "Loại container" không tải khi thêm cont; hộp thoại xóa container không báo thành công, dữ liệu không đổi.
8. Panel "Cần bổ sung": yêu cầu ẩn khi mở trang + hiện sau bấm mâu thuẫn với quy tắc phải hiện trước khi bấm.

**Điều phối (3.6.1, 3.6.3, 4.1.2, 4.1.3, 4.1.7)**
9. Kế hoạch Tổng quát: tìm Bill/Booking trả "0 lô".
10. Bản mẫu còn mâu thuẫn cột phân bổ nhà xe ↔ cột chọn lô.
11. Kế hoạch Chi tiết Xe: cột THAO TÁC còn mâu thuẫn quy cách (~44–48px so với ~144px) — cần thống nhất một lần.
12. Hộp thoại "Chỉnh sửa điều phối" chưa chốt gộp Phân loại + Cước thu dự kiến cùng hàng.
13. ~~Nút Gộp hàng / thanh chọn nổi dùng emoji `📦`, chưa đổi biểu tượng vector; thiết kế Gộp hàng ngày 23/10 chưa triển khai~~ — HOÀN THÀNH 27–28/10: icon vector + full flow Gộp hàng (theo 3.6.3, 4.1.7).
14. Kế hoạch Chi tiết Xe thiếu bộ lọc Loại hàng → lô LCL ngoài trang 1, không tiếp cận được gộp hàng.
15. ~~Nhãn `Lẻ · Ghép (k/N)` vỡ layout; tag phân loại tràn sang cột kế~~ — ĐÃ SỬA theo bố cục SIL-552 (28/10).

**Lái xe (4.2.7)**
16. Còn một dòng hiển thị "MÃ CHUYẾN …" — cần bỏ.

**Danh mục (4.3.3, 4.3.4)**
17. Ô chọn danh mục lọc sai khi tìm chuỗi con (kết quả chính xác không ra).
18. Màn nhà máy bỏ cột TRẠNG THÁI/STT theo quyết định 24/10 chưa kiểm chứng.

**Hiển thị chung (4.1.2, 4.4.3)**
19. ~~Giao diện dữ liệu mobile chưa đạt chuẩn elegant, data-dense~~ — HOÀN THÀNH 29/10 theo chuẩn mobile production grade (10.9.10) cho CUS, Điều vận, Điều phối, Dashboard.
20. Mật độ hộp thoại chưa thống nhất.

### 10.10.2 Yêu cầu giao diện từ mockup chưa có trong spec

Các yêu cầu dưới đây lấy từ 6 file mockup, chưa thấy trong spec hiện hành — cần đưa thành yêu cầu chính thức trước khi làm:

- Bảng danh sách container **inline trong form khởi tạo** (repeater với đầy đủ cột) — chưa chốt: form tạo lô có bảng cont inline hay chỉ ở chi tiết lô.
- Cửa sổ **"Phân bổ phương tiện"** trên `/dispatch` (chia 1 lô FCL nhiều nhà xe + validation tổng phân bổ) — khác hoàn toàn cửa sổ "Gán xe nhóm" hiện có, không được gộp lẫn.
- Bộ lọc **multi-select Điểm Nâng / Hạ / Trả** và **khung giờ (Từ giờ – Đến giờ)** trên `/dispatch-detail`.
- Quyền **CUS cập nhật biển số xe ngoài** khi điều vận để trống — chưa thành luật (cần chốt quyền ghi của CUS trên cột BKS).
- **Tab "Hóa đơn kết hợp"** trên `/shipments` (placeholder ẩn/chưa bật); lưu ý ràng buộc hợp đồng: chưa có trong hợp đồng.
- Cột **Trạng thái phơi phiếu (3 giá trị)** + **Kế toán duyệt (timestamp)** ngay trên lưới CUS.
- Cột **"Tổng thu Khách (Không Hóa đơn)"** (Ops ẩn, CUS xem) — khác khái niệm "không hóa đơn" của chi phí lái xe, không được đồng nhất.
- Nhóm cột cước (đầu ra / đầu vào / chi hộ) với sub-cột Số hóa đơn, ô 2 dòng tiền + số HĐ — rất data-dense, hợp hướng 10.8.2.
- Tìm kiếm **4–5 số cuối** Bill/Tờ khai.
- Ràng buộc API `/dispatch`: chỉ lô "Sẵn sàng điều xe", lô "Chờ chốt lịch" không xuất hiện — ghi thành tiêu chí nghiệm thu.
- Trigger trạng thái: đủ mọi container có BKS → lô "Đã phân xe"; push app lái xe ngay khi 1 dòng xe nhà gắn BKS (hiện push gắn với phát lệnh).
- Tự sinh trạng thái khi tạo lô: trống ngày → "Chờ chốt lịch"; đủ ngày → "Sẵn sàng điều xe" — chưa thành tiêu chí nghiệm thu.
- Cảnh báo "đến ngày vận chuyển mà chưa có xe → chữ đỏ"; mặc định lọc Today→Today khi mở màn chi tiết container.
- Nút **[Khóa Lô]** + **[Đề nghị điều chỉnh]** trên lưới CUS; luồng người mở khóa (Admin) chưa có trong spec.
- Ghi chú Điều xe + Ghi chú Thu khách = 2 ô riêng trên form — chưa map vào field nào.
- Nút `[+]` thêm nhiều ngày giao (hàng lẻ, chia lô nhỏ).

### 10.10.3 Mâu thuẫn cần chủ dự án xác nhận

1. **Tờ khai**: mockup có ô nhập tờ khai cấp lô ở form; quyết định ngày 26/10 bỏ nhập cấp lô, tờ khai per-cont. Quyết định thắng — không reintroduce ô tờ khai cấp lô.
2. **Màn `/shipments`**: mockup A = bảng 2 lớp expandable; mockup B = danh sách phẳng + inline-edit; spec hiện hành = phẳng + ngăn trượt dùng chung form. Ba cách, cần một lựa chọn.
3. **Phân bổ nhà xe FCL** (mockup) vs **"Gán xe nhóm" LCL** (hiện có): hai popup khác nhau, không gộp lẫn; mockup còn đề xuất bỏ cột CHỌN → đụng nút Gộp hàng.
4. **Taxonomy trạng thái lô**: 4 trạng thái của mockup vs chuỗi 6 trạng thái vận hành vs 3 chip hiện hành — cần một bảng trạng thái duy nhất.
5. **Trạng thái phơi phiếu**: 3 giá trị của mockup CUS vs "đã nhận / chưa nhận phơi" của kế toán — cần đối chiếu 2 bộ có phải một không.
6. **Thứ tự trường form tạo lô**: khối (block) của mockup vs band đã chốt — band thắng.
7. **Quyền ghi biển số xe ngoài**: điều vận để trống, CUS điền (mockup) vs hiện hành CUS chỉ auto-fetch — cần chốt.
8. **Mật độ cột THAO TÁC**: xếp dọc ~44–48px vs quy cách cũ ~144px.

### 10.10.4 Thông tin mockup chưa rõ

- Route ghi `/shipment-details` — khác chữ ký route hiện hành; nhiều khả năng là cách ghi, không phải màn mới.
- Dropdown "Kế hoạch: trạng thái" trên `/shipments` — giá trị không liệt kê.
- Cột "TRẠNG THÁI" của bản phẳng — "các trạng thái cần lưu ý", không liệt kê giá trị.
- Sau auto-split, tên nhà xe pre-fill cho từng dòng cont: "ngẫu nhiên" hay theo phân bổ — file mockup không giải thích.
- Vị trí cảnh báo "Trống Xe" trong file mockup ghi sai đánh số cột/dòng.
