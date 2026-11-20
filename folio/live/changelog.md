# Silversea — Business Logic Changelog

## 29/10/2026 — Mobile UX production grade (toàn hệ thống)

- Chuẩn mobile mới áp dụng toàn app: mobile-first dưới 768px chuyển sang dạng thẻ, chữ không cắt cụt, vùng chạm tối thiểu 44px, ô nhập từ 16px để tránh iOS tự phóng, tương phản chữ đạt AA. Mục tiêu: mobile data-dense ở mức production grade.
- CUS: hàng đợi phê duyệt trên mobile, danh mục nhân sự, hồ sơ thu hộ, gợi ý khi nhập liệu, ảnh chụp chứng từ — đều về chuẩn trên.
- Điều vận: phân công xe, tổng quan ngày, chi tiết chuyến, ghi chú nội bộ — card mobile dày đặc, không lãng phí chỗ.
- Điều phối: kế hoạch tổng quát và chi tiết xe trên 768px không còn vỡ dòng, phân loại hiển thị gọn một nhãn.
- Dashboard: các thẻ số liệu xếp lại cho mobile, số lớn không tràn khung.
- Cải thiện hiệu năng dashboards (bỏ render thừa khi lọc).

## 29/10/2026 (bản phát hành) — datetime CUS, gộp lô điều vận, bảo mật

- 686–688 (CUS): Tổng quan hiển thị ngày giờ đóng/trả cho lô hàng lẻ (fallback EDD chỉ áp dụng LCL, FCL giữ luật riêng); tạo lô lẻ dùng trường "Ngày giờ đóng trả" (ngày + giờ) thay "Ngày giao hàng"; bộ lọc theo ngày loại các lô chưa nhập ngày.
- 689–691 (Điều vận): Kế hoạch tổng quát cờ "Lẻ" đúng ở ô hàng hóa; lô đã ghép trả-ĐV hiển thị "Lẻ · Ghép"; nút Gộp hàng chỉ bật ở dòng hợp lệ; lô đã ghép khóa thao tác gộp lặp; phát lệnh theo nhóm ghép.
- 692 (CUS): chức năng xác nhận hoàn thành chuyến xe ngoài trên Chi tiết lô + drawer.
- Bảo mật: nâng zod lên 4.6.7 toàn hệ thống (đóng 4 cảnh báo HIGH) và systeminformation 5.33.18 (đóng 3 cảnh báo qua telemetry).

## Quyết định chủ dự án (29/10/2026)

- **Điều vận được sửa số tờ khai** (trước đây chỉ Quản trị/CUS/Quản lý): số tờ khai là dữ liệu vận hành hàng ngày của điều vận. Cơ sở để SIL-551/553 chấm PASS. Cập nhật §10.6.7.

## 28/10/2026 — Luồng Gộp hàng LCL (Điều vận & CUS)

- Chốt tách biệt hai tầng gộp: gộp xe của Điều vận (tính cước trả nhà xe — Loại xe, Nhà xe, BKS thực, Cước trả ĐV) và gộp hàng của CUS (tính cước thu khách — Loại xe thu, Giá cước, BKS báo khách). Hai nhóm độc lập hoàn toàn, gộp phía này không kéo phía kia.
- Bỏ khái niệm biển số ảo khỏi màn Điều vận: popup Gán xe nhóm chỉ còn 4 trường (Loại xe tính cước trả · Nhà xe · BKS thực · Cước trả ĐVVC).
- Mặc định mỗi lô hàng lẻ = 1 chuyến xe riêng về cước thu; CUS khai báo 3 trường trên dòng (Loại xe thu · Giá cước thu · BKS báo khách — để trống thì lấy BKS thực).
- Chế độ Gộp hàng trên giao diện: cột chọn mặc định ẩn, nút Gộp hàng trên thanh lọc bật/tắt, chỉ chọn được dòng hàng lẻ, thanh nổi tổng hợp dưới đáy màn hình, tự ẩn khi xong.
- CUS gộp chỉ được trong cùng một khách hàng; sau gộp Lô 1 nhận 100% cước thu, các lô còn lại 0₫ với tag ghép; có nút Tách nhóm.
- Luật 100/0 chiều thu chính thức chốt theo tài liệu điều chỉnh 23/10 (trước đây ghi "chưa chốt").

## 28/10/2026 (cập nhật đặc tả — không đổi nghiệp vụ)

- Tái cấu trúc wiki hoàn tất: yêu cầu giao diện tách riêng thành **Chương 10 (10.1–10.10)**; **Chương 9** trở thành chuyên sâu LCL với đánh số lại **9.1–9.8**.
- Sửa tham chiếu chéo số liệu cũ: 5 chỗ `9.x` trong Chương 10 → `10.x`; `§7.8` ở Chương 6 → `§7.6`.
- Chương 7: khôi phục 2 bảng bị hỏng định dạng (§7.2.1 CUS và §7.3 đối chiếu REQ-01..23 — mất dấu xuống dòng khi cập nhật sáng nay), trả lại đầy đủ mã REQ/YC; đánh số lại mục 7.5–7.6 (trước đây nhảy 7.6/7.8).
- Ảnh sơ đồ chuyển hết sang CDN công khai `bot.tingting.vip/wiki-assets` — không còn phụ thuộc route tệp có xác thực của book.tingting.vip.
- Trang chủ: mục lục bổ sung Chương 9–10, sơ đồ đường đọc kéo dài tới 10.

## 27/10/2026 (bản phát hành gần nhất)

- Phần BKS nhóm ở màn điều vận đã gỡ bỏ hoàn toàn chế độ "BKS báo khác": giờ chỉ còn BKS thực và BKS báo khách (ảo). Khi đổi BKS nhóm, hệ thống chặn việc gõ tay "Bổ sung sau".
- Checkbox chế độ gộp hàng giờ ẩn theo mặc định.
- Khi hủy ghép hoặc tách nhóm, lô được tách ra sẽ khôi phục đúng Loại xe ban đầu.
- Cột Số tờ khai xuất hiện ở mọi bảng liệt kê container (trang dispatch-detail cùng tất cả các bảng theo dòng), cho phép click để sửa trực tiếp; ở màn /shipments, cột CHỨNG TỪ hiển thị tất cả số tờ khai của lô.
- Toàn hệ thống: phím ←/→ cuộn ngang mọi bảng; nút Gộp hàng dùng icon thật thay cho emoji.
- Màn tạo lô hàng chuyển sang dạng toàn trang data-dense với bảng Thông tin hàng cũng dense; cột THAO TÁC xếp stack dọc — nút send phía trên, nút ⋯ phía dưới, hành động "Hoàn thành" được chuyển vào menu ⋯.
- Nền toàn ứng dụng đổi sang màu SAGE #E3E8E5.
- Với cột Số tờ khai, việc nhập ở cấp lô đã bị hủy; key declarationNumber cũng bị bỏ khỏi payload tạo lô.
- Nhãn Kho CFS/Nhà máy đổ hiển thị đúng giá trị thực tế.

## 26/10/2026 (bản phát hành gần nhất)

- Tờ khai theo container ra đời với schema customs_declaration_no: POST tự gán một tờ khai, PUT hỏi ghi đè hay giữ nguyên, PATCH áp cho từng container đơn lẻ.
- Debit note cho xe ảo cùng bộ quy tắc hiển thị BKS mới ra mắt.
- Tính năng gộp/tách cước thu khách kèm cơ chế kế thừa của lô chính (survivor inheritance) được bật.
- Kế hoạch Tổng quát trên mobile chuyển sang data-dense.
- Toàn ứng dụng áp dụng các chuẩn chung: cấm cắt chữ (truncate), data-dense, cột THAO TÁC xếp stack, sticky footer một dòng, và alignment đồng nhất trên các biểu mẫu.
