{
  "id": "01M5Z3HFZQFJWC7XY63GJY0M15",
  "space": "silversea",
  "path": "business-logic-changelog.md",
  "kind": "doc",
  "title": "Silversea — Business Logic Changelog",
  "order": 0,
  "status": "published",
  "updatedAt": "2026-10-27T16:54:55.491Z",
  "markdown": "# Silversea — Business Logic Changelog\n\n## 27/10/2026 (bản phát hành gần nhất)\n- **BKS nhóm (điều vận)**: gỡ bỏ hoàn toàn \"BKS báo khác\" — chỉ còn BKS thực + BKS báo khách (ảo). Đổi BKS nhóm chặn gõ tay \"Bổ sung sau\".\n- **Gộp hàng**: checkbox chế độ gộp ẨN mặc định.\n- **Hủy ghép / tách nhóm**: lô tách ra khôi phục đúng Loại xe.\n- **Tờ khai per-cont**: cột Số tờ khai xuất hiện ở MỌI bảng liệt kê container (dispatch-detail + tất cả bảng theo dòng), click-to-edit; /shipments cột CHỨNG TỪ hiển thị TẤT CẢ số tờ khai của lô.\n- **Global**: phím ←/→ cuộn ngang mọi bảng; nút Gộp hàng dùng icon thật thay emoji.\n- **Tạo lô hàng**: toàn trang data-dense + bảng Thông tin hàng dense; cột THAO TÁC stack dọc — send trên, ⋯ dưới, \"Hoàn thành\" vào menu ⋯.\n- **Nền app**: SAGE #E3E8E5 global.\n- **Cột Số tờ khai**: hủy nhập cấp lô; bỏ key declarationNumber khỏi payload tạo lô.\n- **Kho CFS/Cảng**: label Kho CFS/Nhà máy đổ đúng giá trị.\n\n## 26/10/2026 (bản phát hành gần nhất)\n- Tờ khai theo cont: schema customs_declaration_no, POST auto-assign 1 tag, PUT prompt overwrite/keep, PATCH single-container.\n- Debit note xe ảo + BKS display rules.\n- Gộp/tách cước thu khách + survivor inheritance.\n- Kế hoạch Tổng quát mobile data-dense.\n- Toàn app: CẤM truncate, data-dense, THAO TÁC stack, sticky footer 1 dòng, alignment form.\n"
}