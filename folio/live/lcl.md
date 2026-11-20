# 9. Logic nghiệp vụ Hàng lẻ (LCL)
## 9.1 Định nghĩa & phân loại

Hàng lẻ (LCL) là lô không gắn container cụ thể nào của khách — được vận chuyển bằng xe tải theo trọng tải (từ 1.25T đến 15T) hoặc gom chung container 20'/40' chạy ghép. Ngược lại, FCL là lô gắn container có số riêng (MSKU…, 20DC/40DC…).

Mọi bảng đều có badge phân loại Nhập·Cont / Nhập·Lẻ / Xuất·Lẻ, bắt buộc phải phân biệt rõ hàng lẻ với hàng container.

Một dòng hàng lẻ có cụm thông số dạng "Lô hàng lẻ | Thu: Xe 3.5T | Trả: Xe 10T"; xe thu và xe trả có thể khác loại nhau.

Một dòng ghép mang tag "Lẻ · Ghép (n/N)", trong đó n là vị trí của lô trong nhóm và N là tổng số lô ghép.

## 9.2 Tạo lô hàng lẻ

Khi chọn Loại hàng = Hàng lẻ, hệ thống không bắt nhập số container; người dùng chỉ cần nhập 4 trường: Quy cách đóng gói, Số lượng, Trọng lượng (kg) và Thể tích (CBM).

Số Bill/Booking và Hãng tàu khai báo như FCL; trường Hình thức XNK là bắt buộc.

Số tờ khai được quản lý theo container, không còn ô nhập ở cấp lô — ô này đã bị gỡ khỏi form tạo/sửa và dialog Chứng từ; phía backend chặn key declarationNumber trong payload tạo lô và trả lỗi 400.

Ô Kho lấy hàng (CFS/Cảng) tìm kiếm khớp cả full mã (GLC) lẫn prefix (LC).

Về quy tắc container: hàng lẻ đi bằng xe tải luôn chạy 100% xe ngoài (chặn BKS nội bộ, trả 400); hàng lẻ gom cont 20'/40' thì dùng được cả xe nội bộ lẫn xe ngoài. Khi ghép, các dòng anh em còn trống sẽ kế thừa giá trị theo luật /521 — chỉ điền vào dòng trống, không ghi đè giá trị đã khác nhau.

## 9.3 Danh mục & bảng giá

Danh mục vehicle_size_classes gồm: 1.25T, 2.5T, 3.5T, 5T, 8T, 10T, 15T, CONT20, CONT40 (CRUD tại /config/vehicle-size-classes).

Bảng giá được xây theo Tuyến × Khách hàng/Nhà thầu, gồm cước thu và cước trả theo từng trọng tải.

Cước thu/trả dự kiến hiển thị trên dialog Chỉnh sửa điều phối; ở chế độ dense, Phân loại và Cước thu nằm cùng hàng.

## 9.4 Điều vận: gộp xe đi chung để tính cước trả

Điều vận gộp nhiều lô hàng lẻ đi chung một xe thực tế trong ngày để tính cước trả nhà xe. Nhóm gộp của Điều vận chỉ phục vụ đầu vào — nó không liên quan gì đến cách báo khách hay tính cước thu.

Popup Gán xe nhóm của Điều vận chỉ gồm 4 trường. Loại xe tính cước trả chọn trọng tải xe tải (1.25T–15T) hoặc Cont 20'/40'; nếu chọn xe tải thì chỉ được chọn nhà xe ngoài, nếu chọn Cont 20'/40' thì được chọn cả đội xe nội bộ lẫn nhà xe ngoài. Nhà xe là nhà xe thực tế vận chuyển. BKS thực là biển số xe chạy chuyến — chọn từ nhà xe hoặc gõ mới. Cước trả ĐVVC để trống thì hệ thống tự tra bảng giá trả nhà xe, nhập tay thì lấy theo giá nhập.

Không có khái niệm biển số báo khách ở phía Điều vận — biển số báo khách chỉ tồn tại và được khai báo ở phía CUS.

Với cước trả điều vận trong nhóm, Lô 1 chịu 100% còn các lô từ 2 trở đi là 0₫.

Kế hoạch Tổng quát trên mobile ở chế độ dense: mỗi lô là một card 3 dòng kèm badge lẻ/cont; nút Phân bổ nhà xe dạng compact và tự ẩn khi lô đã được phân. Kế hoạch Chi tiết Xe có ô Container 3 dòng. Cột THAO TÁC xếp stack dọc (nút send phía trên, nút ⋯ phía dưới); hành động "Hoàn thành" và Phát lệnh nằm trong menu ⋯; phím ←/→ cuộn ngang mọi bảng. Cột Số tờ khai xuất hiện ở mọi bảng liệt kê container và cho phép click để sửa.

## 9.5 CUS: mặc định mỗi lô là một xe riêng

Về cước thu khách, mặc định mỗi lô hàng lẻ được tính như một chuyến xe độc lập. Trên từng dòng lô, CUS khai báo 3 thông tin đầu ra: Loại xe thu khách (trọng tải hoặc Cont 20'/40'), Giá cước thu khách (tự tra theo bảng giá thu khách theo loại xe, hoặc nhập tay giá thỏa thuận), và BKS báo khách (chọn từ danh mục hoặc gõ tự do).

Quy tắc BKS báo khách: nếu CUS để trống, hệ thống lấy BKS thực do Điều vận gán để báo khách và in lên Debit Note; nếu CUS nhập thì hệ thống lấy BKS do CUS nhập.

Quy ước đếm (30/10/2026): trên các bề mặt đếm/hiển thị theo đơn vị lô/cont, mỗi lô hàng lẻ tương đương 1 lô cont chỉ có 1 cont (không phải 0, không phải tổng số chuyến); FCL giữ số cont thực. Quy ước này khác luật cước thu (mỗi lô lẻ = 1 chuyến xe riêng về cước thu).

## 9.6 Gộp xe thu khách (rev_group) độc lập với gộp Điều vận

Khi nhiều lô ĐÃ BÁO KHÁCH đi chung một xe, CUS dùng chức năng Gộp hàng riêng của mình để tính cước thu. Nhóm cước thu của CUS và nhóm xe thực của Điều vận là hai cấu trúc hoàn toàn độc lập — gộp ở một phía không bao giờ kéo theo phía kia.

Chỉ được gộp các lô của cùng một khách hàng; khác khách hàng thì hệ thống chặn và báo lỗi.

Sau khi gộp, Lô 1 nhận 100% giá cước thu khách, các lô từ 2 trở đi về 0₫ và mang tag "Ghép thu cước cùng Lô 1". Cung cấp nút Tách nhóm trên dòng đã gộp để hủy gộp về lại từng xe riêng.

## 9.7 Chế độ Gộp hàng trên giao diện (bật – tắt)

Cột chọn (checkbox) mặc định bị ẩn trên cả màn hình Điều vận và màn hình CUS để bảng luôn gọn. Trên thanh lọc có nút "Gộp hàng"; khi bấm, nút chuyển trạng thái (đổi màu hoặc thành "Thoát gộp hàng") và cột checkbox xuất hiện ở đầu bảng.

Ô checkbox chỉ hiển thị trên các dòng hàng lẻ; các dòng hàng container bị làm mờ hoặc ẩn để không tích nhầm.

Khi đã tích ít nhất một dòng, thanh nổi dưới đáy màn hình hiện "Đang chọn N lô: Tổng X tấn | Y CBM — Lô 1 giữ 100% tiền" kèm nút mở popup gộp và nút bỏ chọn. Sau khi xác nhận gộp hoặc thoát chế độ, cột checkbox và thanh nổi tự ẩn, bảng trở lại như ban đầu.

## 9.8 Chứng từ (CUS) — Chi tiết lô hàng

Thông số container hiển thị dạng "Lô hàng lẻ | Thu: Xe 3.5T | Trả: Xe 10T".

Khối phân xe gồm 2 dòng: BKS Thực và ô sửa nhanh BKS Báo khách.

Số tờ khai theo từng container: click để sửa từng dòng; các dòng trong một lô được phép trùng một phần hoặc toàn bộ; khi sửa một dòng, hệ thống không ép đồng bộ các dòng khác.

Dòng hàng lẻ được click-to-edit tờ khai và phân xe như FCL.

Ở màn Tổng quan, cột CHỨNG TỪ hiển thị Bill cùng tất cả số tờ khai của lô.

## 9.9 Kế toán & Debit Note

Khi chốt debit, cột Thông số hiển thị dạng "Lẻ · Thu: 5T / Trả: 10T" hoặc "Ghép cùng Bill…"; phải thu/trả tự động tính 100%/0₫ theo nhóm.

Debit Note cho KHÁCH in BKS BÁO KHÁCH (tuyệt đối không in BKS thực) kèm loại xe thu và chú thích ghép.

Bảng kê cho NHÀ XE in BKS THỰC kèm loại xe trả.

Với hoàn ứng: kế toán lập phiếu; khi replay với cùng idempotency-key, hệ thống trả 200; nếu dùng key khác sau khi đã duyệt thì trả 409.

## 9.10 Nguyên tắc giao diện

Nền toàn ứng dụng dùng màu sage nhạt, card trắng nổi trên nền.

Cấm cắt chữ: mọi ô dữ liệu wrap trọn văn bản — cuộn ngang thay vì cắt ký tự.

Data-dense: card 3 dòng, meta gộp, nút compact, footer hành động một dòng sticky.

Cột THAO TÁC xếp stack dọc; hành động "Hoàn thành" nằm trong menu ⋯.

## Sơ đồ hai tầng gộp độc lập

```mermaid
flowchart LR
 subograph 1["Điều vận — đầu vào (cước trả)"]
  A1["Nhiều lô lẻ trong ngày"] --> B1["Gộp xe thực tế<br/>Loại xe · Nhà xe · BKS thực · Cước trả ĐV"]
 end
 subograph 2["CUS — đầu ra (cước thu)"]
  C1["Mỗi lô = 1 xe riêng<br/>Loại xe thu · Giá cước · BKS báo khách"] --> D1["Tùy chọn: gộp xe thu khách<br/>Lô 1 giữ 100% · còn lại 0₫"]
 end
 B1 -. "độc lập hoàn toàn" .- D1
```

```mermaid
flowchart TD
 A["Lô A: 2.000.000₫<br/>Lô B: 1.500.000₫"] -->|"Gộp xe thu khách<br/>(cùng khách hàng)"| B["Lô A = 2.000.000₫ (100%)<br/>Lô B = 0₫ · tag Ghép thu cước cùng Lô 1"]
 B -->|"Tách nhóm"| C["Khôi phục gốc:<br/>A = 2.000.000₫ · B = 1.500.000₫"]
 B -->|"Xóa Lô A (lô chính)"| D["Lô B KẾ THỪA 100%<br/>= 2.000.000₫ — tiền không mất"]
```

```mermaid
stateDiagram-v2
 direction LR
 Rieng: Lô riêng (100% cước)
 Ghep: Trong nhóm ghép (Lô chính 100% · Lô phụ 0₫)
 Rieng --> Ghep: Gộp (Điều vận hoặc CUS)
 Ghep --> Rieng: Tách nhóm / Xóa lô chính (lô phụ kế thừa)
```
