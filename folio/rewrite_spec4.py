#!/usr/bin/env python3
src = open("src/spec-4.md").read()

P = []

P.append((
"""- **Thành phần:** Cột **CHỌN LÔ**
- **Quy tắc:** Mặc định **ẩn**; hiện khi bật `[Gộp hàng]`; tiêu đề thống nhất “CHỌN LÔ”

- **Thành phần:** **CẢNG NÂNG/HẠ** dòng LCL
- **Quy tắc:** Lấy **Kho lấy hàng / Điểm trả hàng** do CUS nhập; không có thì `—`; không ghi “Chưa có cont”

- **Thành phần:** **TỔNG QUAN HÀNG HÓA**
- **Quy tắc:** `[SL] [Loại bao bì] · [kg] · [CBM]` (VD `5 PALLET · 1.922 kg · 4 CBM`); ẩn CBM khi không có

- **Thành phần:** **PHÂN LOẠI / chiều**
- **Quy tắc:** Badge **NHẬP LẺ / XUẤT LẺ** cho lô LCL

- **Thành phần:** **Phân xe / dòng trống**
- **Quy tắc:** Chưa gán → **1 nhãn mờ “Chưa phân xe”**; dòng trống hiện “Không có hàng lẻ chạy ngày đã chọn”""",
"""- Cột **CHỌN LÔ** mặc định **ẩn**, chỉ hiện khi bật `[Gộp hàng]`, tiêu đề thống nhất “CHỌN LÔ”.
- Cột **CẢNG NÂNG/HẠ** ở dòng LCL lấy **Kho lấy hàng / Điểm trả hàng** do CUS nhập; không có thì hiển thị `—`, không ghi “Chưa có cont”.
- Cột **TỔNG QUAN HÀNG HÓA** hiển thị `[SL] [Loại bao bì] · [kg] · [CBM]` (VD `5 PALLET · 1.922 kg · 4 CBM`) và ẩn CBM khi không có.
- Cột **PHÂN LOẠI / chiều** hiển thị badge **NHẬP LẺ / XUẤT LẺ** cho lô LCL.
- Khi **chưa gán xe**, dòng hiện **1 nhãn mờ “Chưa phân xe”**; dòng trống hiện “Không có hàng lẻ chạy ngày đã chọn”."""))

P.append((
"""- **#:** 1
- **Quyết định chủ sản phẩm:** **CẤM truncate** — mọi ô **wrap full**; header 2 dòng bị đè (“THỜI GIAN &/LỊCH TRÌNH”) phải tách; “Ngày giao 23/10/2026” không đè “Trả hàng”

- **#:** 2
- **Quyết định chủ sản phẩm:** Cột **ĐIỀU PHỐI** tách **5 dòng**: nhà xe · biển số · tài xế · SĐT · trạng thái — không chi tiết nào bị ẩn/cắt

- **#:** 3
- **Quyết định chủ sản phẩm:** Dòng chưa phân nhà xe: **bỏ dòng italic “CUS sẽ bổ sung”**, để trống

- **#:** 4
- **Quyết định chủ sản phẩm:** Cột **PHÂN LOẠI**: tag compact, **1 nhãn/dòng**, header 1 dòng; pill “Lẻ · Ghép (n/2)” không tràn sang cột kế

- **#:** 5
- **Quyết định chủ sản phẩm:** Cột **SỐ TỜ KHAI**, **sửa trực tiếp khi bấm vào ô** (“bấm ô để sửa là đủ, không cần nút Sửa”)

- **#:** 6
- **Quyết định chủ sản phẩm:** Cột **THAO TÁC**: **xếp dọc** (gửi trên, `⋯` dưới), “Hoàn thành” vào menu `⋯`, ~44–48px — còn mâu thuẫn với quy cách ~144px → **thống nhất một lần**

- **#:** 7
- **Quyết định chủ sản phẩm:** **Số container in đậm**, tên cảng chữ thường; ô **Ghi chú** gõ được **Space**""",
"""1. **Cấm truncate** — mọi ô **wrap full**; header 2 dòng bị đè (“THỜI GIAN &/LỊCH TRÌNH”) phải tách; “Ngày giao 23/10/2026” không đè “Trả hàng”.
2. Cột **ĐIỀU PHỐI** tách **5 dòng**: nhà xe · biển số · tài xế · SĐT · trạng thái — không chi tiết nào bị ẩn/cắt.
3. Dòng chưa phân nhà xe: **bỏ dòng italic “CUS sẽ bổ sung”**, để trống.
4. Cột **PHÂN LOẠI**: tag compact, **1 nhãn/dòng**, header 1 dòng; pill “Lẻ · Ghép (n/2)” không tràn sang cột kế bên.
5. Cột **SỐ TỜ KHAI** **sửa trực tiếp khi bấm vào ô** (“bấm ô để sửa là đủ, không cần nút Sửa”).
6. Cột **THAO TÁC** **xếp dọc** (gửi trên, `⋯` dưới), “Hoàn thành” vào menu `⋯`, cao ~44–48px — còn mâu thuẫn với quy cách ~144px, cần **thống nhất một lần**.
7. **Số container in đậm**, tên cảng chữ thường; ô **Ghi chú** gõ được **Space**."""))

P.append((
"""- **Lớp:** **Nhận lệnh**
- **Yêu cầu:** **Không bắt buộc tải ảnh**""",
"""- Ở lớp **nhận lệnh**, **không bắt buộc tải ảnh**."""))

P.append((
"""- **Tình huống:** Nhà máy cũ chưa có tuyến
- **Hành vi:** Cho chọn tuyến hợp lệ, chỉ rõ thiếu; **không phát lệnh** khi tuyến bắt buộc còn thiếu

- **Tình huống:** KH chưa có nhà máy
- **Hành vi:** Giải thích danh sách rỗng, tạo nhanh nếu đủ quyền; **không đưa nhà máy của KH khác**

- **Tình huống:** Ngừng hoạt động / đang tải / lỗi tải
- **Hành vi:** Không chọn cho việc mới (việc cũ vẫn xem); phân biệt tải lỗi với rỗng, cho thử lại

- **Tình huống:** Người khác sửa lúc đang nhập
- **Hành vi:** Giữ nội dung, hiển thị thay đổi — **không ghi đè ngầm**""",
"""- **Nhà máy cũ chưa có tuyến:** cho chọn tuyến hợp lệ và chỉ rõ phần thiếu; **không phát lệnh** khi tuyến bắt buộc còn thiếu.
- **KH chưa có nhà máy:** giải thích danh sách rỗng, tạo nhanh nếu đủ quyền; **không đưa nhà máy của khách hàng khác** vào.
- **Nhà máy ngừng hoạt động / đang tải / lỗi tải:** không chọn cho việc mới (việc cũ vẫn xem); phân biệt tải lỗi với danh sách rỗng và cho thử lại.
- **Người khác sửa lúc đang nhập:** giữ nội dung đang nhập, hiển thị thay đổi — **không ghi đè ngầm**."""))

P.append((
"""- **#:** 1
- **Điểm:** **Bộ lọc Loại hàng (FCL/LCL)** trên `/dispatch-detail`: (A) thêm bộ lọc (khuyến nghị) / (B) đổi thứ tự bảng / (C) hiện lý do nút disable
- 
- **#:** 2
- **Điểm:** **Bộ chứng từ LCL** thay “phiếu hạ bãi + biên bản giao nhận”
- 
- **#:** 3
- **Điểm:** **Bảng mức phụ phí KẸP/KẾT HỢP** cho lương ghép
- 
- **#:** 4
- **Điểm:** **Tải trọng tổ hợp** (trường tải trọng xe luôn để trống → chưa ghép được KẸP)
- 
- **#:** 5
- **Điểm:** **Bên xuất hóa đơn** khi nhiều bên hợp lệ; **danh mục bước bị bỏ qua** của lô lệnh chạy ngoài; **vùng phụ phí mặc định** khi có 2 vùng đang hoạt động
- 
- **#:** 6
- **Điểm:** **Trường quyết định “có điểm trả hàng”** (container nhập khẩu); **cách thay thế mã chuyến thống nhất** cho màn desktop
- 
- **#:** 7
- **Điểm:** **“Bưu kiện”** — không có thực thể tương ứng theo đặc tả hiện có; **mã chuyến còn hiển thị trên màn hình lái xe** — cần bỏ
- 
- **#:** 8
- **Điểm:** **Cột THAO TÁC** — còn mâu thuẫn quy cách xếp dọc (~44–48px so với ~144px); **mật độ hộp thoại** — thống nhất một lần
- """,
"""1. **Bộ lọc Loại hàng (FCL/LCL)** trên `/dispatch-detail`: (A) thêm bộ lọc (khuyến nghị) / (B) đổi thứ tự bảng / (C) hiện lý do nút disable.
2. **Bộ chứng từ LCL** thay “phiếu hạ bãi + biên bản giao nhận”.
3. **Bảng mức phụ phí KẸP/KẾT HỢP** cho lương ghép.
4. **Tải trọng tổ hợp** (trường tải trọng xe luôn để trống → chưa ghép được KẸP).
5. **Bên xuất hóa đơn** khi nhiều bên hợp lệ; **danh mục bước bị bỏ qua** của lô lệnh chạy ngoài; **vùng phụ phí mặc định** khi có 2 vùng đang hoạt động.
6. **Trường quyết định “có điểm trả hàng”** (container nhập khẩu); **cách thay thế mã chuyến thống nhất** cho màn desktop.
7. **“Bưu kiện”** — không có thực thể tương ứng theo đặc tả hiện có; **mã chuyến còn hiển thị trên màn hình lái xe** — cần bỏ.
8. **Cột THAO TÁC** — còn mâu thuẫn quy cách xếp dọc (~44–48px so với ~144px); **mật độ hộp thoại** — thống nhất một lần."""))

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
open("after/spec-4.md", "w").write(src)
print("written", len(src))
