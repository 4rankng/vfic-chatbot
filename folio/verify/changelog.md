# Silversea — Business Logic Changelog

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
