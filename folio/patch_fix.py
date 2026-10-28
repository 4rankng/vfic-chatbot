#!/usr/bin/env python3
def patch(path, pairs):
    s = open(path).read()
    for old, new in pairs:
        n = s.count(old)
        assert n == 1, f"{path}: {n}x -- {old[:60]!r}"
        s = s.replace(old, new)
    open(path, "w").write(s)
    print(f"patched {path}: {len(pairs)} edits")

patch("after/spec-2.md", [
("**Vai trò:** CUS (chứng từ) chịu trách nhiệm chính; Quản trị viên và Quản lý thay khi có quyền.",
 "**CUS (chứng từ) chịu trách nhiệm chính**; Quản trị viên và Quản lý thay khi có quyền."),
("""**Vai trò:** Kế toán (khung giá, kỳ giá dầu), CUS/Điều vận (đọc giá khi nhập lô), người có quyền
quản lý biểu cước (lưu giá gốc, điều khoản tuyến).""",
 "Bước này liên quan **Kế toán** (khung giá, kỳ giá dầu), **CUS/Điều vận** (đọc giá khi nhập lô) và **người có quyền quản lý biểu cước** (lưu giá gốc, điều khoản tuyến)."),
("**Vai trò:** CUS.", "Bước này do **CUS** thực hiện."),
("**Vai trò:** Điều vận.", "Bước này do **Điều vận** thực hiện."),
("**Vai trò:** Lái xe (chủ động), nhà vận tải; Điều vận theo dõi.",
 "**Lái xe chủ động thực hiện** cùng nhà vận tải; Điều vận theo dõi."),
("**Vai trò:** CUS (chủ trì), khách hàng (xác nhận tuỳ chọn).",
 "**CUS chủ trì**; khách hàng tham gia xác nhận tuỳ chọn."),
("""**Vai trò:** Hệ thống (cước tự động), Ops và lái xe (chi phí hiện trường), CUS/Điều vận (phát sinh),
Kế toán (giá cuối, cược, hóa đơn kết hợp).""",
 "**Hệ thống** lo phần cước tự động; **Ops và lái xe** khai chi phí hiện trường; **CUS/Điều vận** ghi phát sinh; **Kế toán** xử lý giá cuối, cược, hóa đơn kết hợp."),
("**Vai trò:** Kế toán (chủ trì), Ops (bảng kê cá nhân), CUS/khách hàng (phản hồi bảng kê).",
 "**Kế toán chủ trì**; Ops lập bảng kê cá nhân; CUS/khách hàng phản hồi bảng kê."),
("**Vai trò:** Kế toán; Quản lý xem số liệu.", "**Kế toán** thực hiện; Quản lý xem số liệu."),
])

patch("after/spec-3.md", [
("- **Quy tắc chặn ô Bill/Booking**: ô bị tắt tới khi chọn Hình thức XNK;",
 "- Ô Bill/Booking bị chặn cho tới khi chọn Hình thức XNK;"),
])

patch("after/spec-4.md", [
("- **Loại xe:** `1.25T · 2.5T · 3.5T · 5T · 8T · 10T · 15T` cạnh `Cont 20'DC / 40'DC / 40'HC`; bảng giá cấu hình **cước thu + cước trả theo từng trọng tải**.",
 "- Danh sách loại xe gồm `1.25T · 2.5T · 3.5T · 5T · 8T · 10T · 15T` đặt cạnh `Cont 20'DC / 40'DC / 40'HC`; bảng giá cấu hình **cước thu + cước trả theo từng trọng tải**."),
])

patch("after/spec-6.md", [
("""**Chứng từ:** phiếu thu · phiếu chi (gắn nguồn quỹ) · Debit Note/bảng kê công nợ (đợt) · hóa đơn kết hợp · phiếu hoàn ứng · yêu cầu tạm ứng (chỉ ghi nhu cầu, *Chưa giao tiền*). **Định dạng tiền:** mọi trường số tiền mặc định 1,000,000, **tất cả phân hệ** (đơn vị VND, áp dụng từ 21/10); số phải hữu hạn, sai định dạng/vượt giới hạn bị chặn **cả ở nhập và lưu** (AC-CP-KT-19).""",
 """Các loại chứng từ gồm phiếu thu, phiếu chi (gắn nguồn quỹ), Debit Note/bảng kê công nợ theo đợt, hóa đơn kết hợp, phiếu hoàn ứng và yêu cầu tạm ứng (chỉ ghi nhu cầu, *Chưa giao tiền*). Về định dạng tiền, mọi trường số tiền mặc định `1,000,000` ở **tất cả phân hệ** (đơn vị VND, áp dụng từ 21/10); số phải hữu hạn, sai định dạng/vượt giới hạn bị chặn **cả ở nhập và lưu** (AC-CP-KT-19)."""),
])

patch("after/spec-7.md", [
("""- **REP-02** — Báo cáo **từng đầu xe nội bộ theo chu kỳ 1 tháng**, % cơ cấu chuyến cho KPI.
- **ENV-01** — (nội dung yêu cầu để trống trong tài liệu gốc).""",
 """- **REP-02** — Báo cáo **từng đầu xe nội bộ theo chu kỳ 1 tháng**, % cơ cấu chuyến cho KPI.

### 7.2.6 ENV — Môi trường (1 YC)

- **ENV-01** — (nội dung yêu cầu để trống trong tài liệu gốc)."""),
])

print("ALL PATCHED")
