# Silversea — Business Logic Changelog

## 27/10/2026 (bản phát hành gần nhất)
- **BKS nhóm (điều vận)**: gỡ bỏ hoàn toàn "BKS báo khác" — chỉ còn BKS thực + BKS báo khách (ảo). Đổi BKS nhóm chặn gõ tay "Bổ sung sau".
- **Gộp hàng**: checkbox chế độ gộp ẨN mặc định.
- **Hủy ghép / tách nhóm**: lô tách ra khôi phục đúng Loại xe.
- **Tờ khai per-cont**: cột Số tờ khai xuất hiện ở MỌI bảng liệt kê container (dispatch-detail + tất cả bảng theo dòng), click-to-edit; /shipments cột CHỨNG TỪ hiển thị TẤT CẢ số tờ khai của lô.
- **Global**: phím ←/→ cuộn ngang mọi bảng; nút Gộp hàng dùng icon thật thay emoji.
- **Tạo lô hàng**: toàn trang data-dense + bảng Thông tin hàng dense; cột THAO TÁC stack dọc — send trên, ⋯ dưới, "Hoàn thành" vào menu ⋯.
- **Nền app**: SAGE #E3E8E5 global.
- **Cột Số tờ khai**: hủy nhập cấp lô; bỏ key declarationNumber khỏi payload tạo lô.
- **Kho CFS/Cảng**: label Kho CFS/Nhà máy đổ đúng giá trị.

## 26/10/2026 (bản phát hành gần nhất)
- Tờ khai theo cont: schema customs_declaration_no, POST auto-assign 1 tag, PUT prompt overwrite/keep, PATCH single-container.
- Debit note xe ảo + BKS display rules.
- Gộp/tách cước thu khách + survivor inheritance.
- Kế hoạch Tổng quát mobile data-dense.
- Toàn app: CẤM truncate, data-dense, THAO TÁC stack, sticky footer 1 dòng, alignment form.
