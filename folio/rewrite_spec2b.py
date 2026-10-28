#!/usr/bin/env python3
# Rewrite spec-2 part B: validation table + exception sections + open points.
src = open("after/spec-2.md").read()

P = []

# ---- Block 9: §2.5.1 validation V01-V32 -------------------------------------
v_old = []
v_new = []
VAL = [
("V01", "Cổng Bill/Booking: chỉ ghi một trong số Bill hoặc Booking", "Tạo/sửa lô", "Ô bị tắt cho tới khi chọn Hình thức xuất nhập khẩu trước; không bao giờ ghi cả hai"),
("V02", "Hãng tàu chỉ hiển thị với FCL", "Tạo/sửa lô", "Ẩn trường"),
("V03", "Trường bắt buộc còn trống khi lưu", "Mọi biểu mẫu nhập", "Viền đỏ tại đúng ô + thông báo gắn đúng trường"),
("V04", "Số lượng/đơn giá/phụ cấp trên biểu mẫu chuyến **không âm**", "Nhập chuyến", "Chặn; riêng dòng chi phí âm theo luật ở §2.4.5"),
("V05", "Số tiền: hữu hạn, đúng định dạng, không vượt giới hạn lưu trữ", "Nhập tiền (cả nhập và lưu)", "Chặn cả hai tầng; 0 ₫ thu khách giữ chủ ý; số tiền chi không rỗng/0 khi khai thực chi"),
("V06", "Điều kiện phát lệnh: phân bổ + lịch + xe + tài xế + moóc phù hợp; xe/người đang hoạt động, đủ sức chở, không xung đột", "Phát lệnh", "Chặn phát lệnh, lỗi hiện tại dòng kế hoạch"),
("V07", "Xung đột lịch (cùng đầu xe/khung giờ)", "Gán xe", "Dấu hiệu yếu (chỉ có ngày): cảnh báo + “Vẫn lưu?”; đủ hai dấu thời gian: **chặn cứng**"),
("V08", "Tổng phân bổ ≤ số lượng từng loại; thêm phân bổ không nhân đôi công việc", "Phân bổ", "Chặn"),
("V09", "Kẹp: tổng tải đồng thời ≤ tải cho phép; không thêm thành viên thứ 3; lộ trình khả thi", "Ghép cặp", "Chặn"),
("V10", "Kết hợp: Lệnh 1 chưa xong → chặn Lệnh 2; hai số vỏ khác nhau ≠ cùng vỏ", "Ghép nối tiếp", "Chặn / yêu cầu bổ sung"),
("V11", "Hoàn thành chuyến: đã tự nhận lệnh + đủ 2 nhóm bằng chứng; ảnh mở lại được", "Hoàn thành", "Chặn, nêu thiếu gì; e-POD ảnh là tuỳ chọn"),
("V12", "Chống lặp: bấm lặp/thử lại không sinh trùng lô/chuyến/ảnh/tiền/phiếu/phân bổ", "Mọi thao tác ghi", "Trả về kết quả đã ghi, không tạo bản sao"),
("V13", "Phiếu quỹ: mọi dòng còn hợp lệ, cùng kỳ, không vượt số còn lại", "Ghi phiếu", "**Hủy toàn bộ thay đổi trong giao dịch** nếu thiếu khai báo nghiệp vụ hoặc không ghi được nhật ký [AC-CP-KT-20]"),
("V14", "Nguồn quỹ khớp dòng chi", "Ghi phiếu", "Sai nguồn → phiếu bị từ chối + nêu đúng dòng sai; trộn 2 nguồn → từ chối + yêu cầu tách phiếu"),
("V15", "Thu không vượt phải thu", "Ghi thu", "Chặn, không âm ngầm [AC-CP-KT-10]"),
("V16", "Ghi chú lý do bắt buộc khi thu khách 0 ₫", "Khai chi phí Ops", "Chặn lưu"),
("V17", "Nhập trùng chi phí Ops", "Khai chi phí", "Báo lỗi trùng lặp + bảng xác nhận 2 nút; dòng đã hủy không cảnh báo"),
("V18", "Số hóa đơn bắt buộc với nhóm “yêu cầu hóa đơn”", "Nhập chi phí", "Chặn; không chấp nhận bằng chứng thay thế ở nhóm này"),
("V19", "Kỳ kế toán: không ghi vào kỳ đã khóa", "Quyết toán/ghi tiền", "Chặn + nêu lý do; hồ sơ khóa không sửa đè"),
("V20", "Lô đã thuộc bảng kê khác", "Chọn lô vào bảng kê/đợt", "Chặn + nêu số lô"),
("V21", "Điều kiện chốt debit: có ngày giao; xác định được số thu/trả; không còn yêu cầu điều chỉnh cước chờ; số lần chưa dùng trong tháng+chiều của KH; chưa thuộc đợt khác", "Chốt debit", "Chặn + nêu rõ lô/việc cần làm"),
("V22", "Yêu cầu điều chỉnh cước đang chờ", "Xuất debit", "Lô không xuất được debit, nêu mã lô"),
("V23", "Cược: `0 ≤ đã hoàn ≤ số cược`; đã hoàn > 0 phải có ngày nhận", "Ghi hoàn cược", "Chặn"),
("V24", "Cảnh báo cược quá hạn", "Theo dõi cược", "2 cảnh báo song song: lô quá **7 ngày** chưa có ngày nộp CV; tổng “Chưa hoàn cược số tiền: …”. **Chưa chốt:** mốc bắt đầu và cách nhắc của cảnh báo quá hạn cược"),
("V25", "Không hiển thị mã kỹ thuật", "Mọi màn hình", "`SHP-*`, `TRP-*`, mã chứng từ, số `#` **không bao giờ hiển thị**; thiếu khóa nghiệp vụ → “—”, không tự chế số thay thế"),
("V26", "Phân quyền", "Mọi thao tác", "Quyền theo vai/tổ chức/phân công/đối tượng; biết mã hay từng mở link **không** cấp quyền; khách hàng không xem khách khác; lái xe/Ops mất quyền cũ khi phân công đổi"),
("V27", "Phạm vi ghi chi phí", "Khai chi phí", "Chi phí chỉ ghi được trong phạm vi quyền của vai; thiếu quyền ghi thì bị chặn, không nới lỏng"),
("V28", "Sổ quỹ Ops chỉ-đọc theo phạm vi", "Xem sổ quỹ", "Hệ thống tự thu hẹp dữ liệu theo người đăng nhập, không nhận thông tin định danh do phía người dùng gửi lên"),
("V29", "Đồng thời: hai người sửa cùng dữ liệu", "Mọi biểu mẫu dài", "Không ghi đè âm thầm; biết thay đổi liên quan, giữ nội dung đang nhập, người dùng tự chọn cách tiếp tục"),
("V30", "Danh sách “tải lỗi” ≠ “tải rỗng”", "Mọi màn hình", "Hai trạng thái khác nhau, có cách thử lại"),
("V31", "Phản hồi trung thực", "Mọi thao tác", "Chỉ báo “đã lưu” khi mở lại còn đúng; lỗi cạnh trường cần sửa; không báo thành công giả"),
("V32", "Responsive", "Mọi màn hình", "390px / 820px / desktop; bộ lọc & trường tiền cùng cỡ, không tràn, không thẻ lồng thẻ, thao tác bàn phím được [AC-CP-KT-21]"),
]
for vid, chk, stage, behavior in VAL:
    v_old.append(f"""- **#:** {vid}
- **Điểm kiểm tra:** {chk}
- **Giai đoạn:** {stage}
- **Hành vi khi vi phạm:** {behavior}""")
    v_new.append(f"- **{vid}** ({stage.lower() if stage[0].isupper() else stage}) — {chk}. Khi vi phạm: {behavior}")

old_table = "\n\n".join(v_old)
new_table = "\n".join(v_new)
P.append((old_table, new_table))

# ---- Block 10: §2.6.1 mất kết nối -------------------------------------------
P.append((
"""- **Tình huống:** Mất mạng khi thao tác
- **Hành vi bắt buộc:** Báo rõ **chưa thể lưu**; giữ nội dung đang nhập khi còn có thể; nói rõ thông tin hiển thị có thể chưa mới
- **Cấm:** Không báo đã lưu; không nhận nghiệp vụ để gửi sau

- **Tình huống:** Mạng phục hồi
- **Hành vi bắt buộc:** Người dùng **chủ động** tiếp tục
- **Cấm:** Hệ thống **không** tự gửi lại thao tác cũ khi nối mạng/mở lại/đổi tài khoản

- **Tình huống:** Chưa rõ lần trước lưu thành công
- **Hành vi bắt buộc:** Giúp người dùng xác định kết quả trước khi thử lại
- **Cấm:** Không tạo bản ghi trùng

- **Tình huống:** Hệ thống không khả dụng
- **Hành vi bắt buộc:** Lỗi kết nối + **giữ nội dung chưa lưu** để thử lại
- **Cấm:** Không kiểm tra kết nối định kỳ trước thao tác, không tự gửi lại thao tác

- **Tình huống:** Lỗi tạm thời
- **Hành vi bắt buộc:** Giữ phiên + nút thử lại
- **Cấm:** **Không** mô tả thành hết phiên đăng nhập nếu tài khoản còn hợp lệ""",
"""- **Mất mạng khi thao tác:** hệ thống phải báo rõ **chưa thể lưu**, giữ nội dung đang nhập khi còn có thể và nói rõ thông tin hiển thị có thể chưa mới. Cấm báo đã lưu khi chưa lưu được, và cấm nhận nghiệp vụ để gửi sau.
- **Mạng phục hồi:** người dùng **chủ động** tiếp tục. Cấm: hệ thống **không** tự gửi lại thao tác cũ khi nối mạng, mở lại hay đổi tài khoản.
- **Chưa rõ lần trước lưu thành công hay chưa:** giúp người dùng xác định kết quả trước khi thử lại; cấm tạo bản ghi trùng.
- **Hệ thống không khả dụng:** báo lỗi kết nối kèm **giữ nội dung chưa lưu** để thử lại. Cấm kiểm tra kết nối định kỳ trước thao tác và cấm tự gửi lại thao tác.
- **Lỗi tạm thời:** giữ phiên và nút thử lại. Cấm **kết thúc phiên đăng nhập** khi tài khoản còn hợp lệ."""))

# ---- Block 11: §2.6.2 sửa đổi sau khi đã chốt --------------------------------
P.append((
"""- **Đối tượng:** **Lô đã khóa kế toán**
- **Quy tắc xử lý:** Sửa chi phí bị chặn; các trường theo dõi thực tế (ngày nộp hồ sơ hoàn cược, ngày tiền về, số đã hoàn) vẫn bổ sung được; danh mục đổi sau khóa không viết lại chứng từ đã phát hành. **Ghi chú** CUS/quản trị/điều vận vẫn sửa được nhưng **không** bỏ qua ràng buộc giai đoạn tiếp nhận của Điều vận

- **Đối tượng:** **Tờ khai trên lô khóa**
- **Quy tắc xử lý:** Nút hiện nhưng bị tắt kèm lý do (“Lô hàng đã khóa kế toán; không thể sửa tờ khai.”)

- **Đối tượng:** **Kỳ kế toán đã khóa**
- **Quy tắc xử lý:** Không tự mở kỳ, không tự thay số tiền đã chốt; lịch sử quyết định cũ đọc được

- **Đối tượng:** **Khoản chi đã có số hóa đơn**
- **Quy tắc xử lý:** Khóa trên màn quyết toán; muốn đổi phải sửa tại **nguồn chi phí**

- **Đối tượng:** **Khoản chi đã đối chiếu/hủy/khóa kỳ**
- **Quy tắc xử lý:** Điều chỉnh bằng **khoản thay thế liên kết** (lý do, người sửa, thời điểm); gốc giữ nguyên số tiền + chứng từ; nghĩa vụ cũ đảo bằng **bút toán**

- **Đối tượng:** **Đợt hoàn ứng**
- **Quy tắc xử lý:** Sửa → kế toán hoàn tác đợt với lý do **sau khi đảo các phiếu tiền liên quan**; đợt cũ vẫn tra cứu; không còn nút trả/thu tiền trên đợt đã hoàn tác

- **Đối tượng:** **Cước đã khóa / chứng từ đã phát hành**
- **Quy tắc xử lý:** Kỳ giá mới không đổi cước đã khóa; đổi Ngày vận chuyển hợp lệ → thấy ảnh hưởng, lưu bản kế, giữ bản cũ; chứng từ phát hành **không tự đổi theo** — điều chỉnh chứng từ là thao tác riêng có quyền + lý do

- **Đối tượng:** **Giá cuối trên bảng kê**
- **Quy tắc xử lý:** Giữ cước hợp đồng để so sánh; lý do bắt buộc; không ghi đè

- **Đối tượng:** **Bảng kê/debit đã chốt**
- **Quy tắc xử lý:** Khoản mới không tự chen vào bảng kê đã chốt; lô đã khóa số liệu không nhận yêu cầu điều chỉnh cước mới

- **Đối tượng:** **Phiếu đã ghi**
- **Quy tắc xử lý:** Hủy/đảo phiếu cần quyền + lý do + dấu vết; không xóa lịch sử""",
"""- **Lô đã khóa kế toán:** sửa chi phí bị chặn; các trường theo dõi thực tế (ngày nộp hồ sơ hoàn cược, ngày tiền về, số đã hoàn) vẫn bổ sung được; danh mục đổi sau khóa không viết lại chứng từ đã phát hành. **Ghi chú** của CUS/quản trị/điều vận vẫn sửa được nhưng **không** bỏ qua ràng buộc giai đoạn tiếp nhận của Điều vận.
- **Tờ khai trên lô khóa:** nút vẫn hiện nhưng bị tắt kèm lý do (“Lô hàng đã khóa kế toán; không thể sửa tờ khai.”).
- **Kỳ kế toán đã khóa:** không tự mở kỳ, không tự thay số tiền đã chốt; lịch sử quyết định cũ đọc được.
- **Khoản chi đã có số hóa đơn:** khóa trên màn quyết toán; muốn đổi phải sửa tại **nguồn chi phí**.
- **Khoản chi đã đối chiếu/hủy/khóa kỳ:** điều chỉnh bằng **khoản thay thế liên kết** (lý do, người sửa, thời điểm); bản gốc giữ nguyên số tiền + chứng từ; nghĩa vụ cũ đảo bằng **bút toán**.
- **Đợt hoàn ứng:** khi sửa, kế toán hoàn tác đợt với lý do **sau khi đảo các phiếu tiền liên quan**; đợt cũ vẫn tra cứu; không còn nút trả/thu tiền trên đợt đã hoàn tác.
- **Cước đã khóa / chứng từ đã phát hành:** kỳ giá mới không đổi cước đã khóa; đổi Ngày vận chuyển hợp lệ thì thấy ảnh hưởng, lưu bản kế, giữ bản cũ; chứng từ phát hành **không tự đổi theo** — điều chỉnh chứng từ là thao tác riêng có quyền + lý do.
- **Giá cuối trên bảng kê:** giữ cước hợp đồng để so sánh; lý do bắt buộc; không ghi đè.
- **Bảng kê/debit đã chốt:** khoản mới không tự chen vào bảng kê đã chốt; lô đã khóa số liệu không nhận yêu cầu điều chỉnh cước mới.
- **Phiếu đã ghi:** hủy/đảo phiếu cần quyền + lý do + dấu vết; không xóa lịch sử."""))

# ---- Block 12: §2.6.5 ngoại lệ thường gặp ------------------------------------
P.append((
"""- **Tình huống:** Giá dầu kỳ < giá mốc
- **Xử lý:** Phụ phí dầu = 0 (0 thật, hợp lệ) — khác với thiếu tham số → phải nói rõ, không tự 0

- **Tình huống:** Mở kỳ giá dầu mới
- **Xử lý:** Không đổi cước đã phát hành; lô phát sinh trong lúc chờ “Để sau” giữ giá cũ

- **Tình huống:** Thiếu giá gốc 15T / thiếu lag / ngưỡng / kỳ giá
- **Xử lý:** Báo thiếu đúng phần; không dùng 0, số minh hoạ hay giá tuyến/loại xe khác

- **Tình huống:** Chưa có Ngày vận chuyển
- **Xử lý:** Lưu được thông tin lô; biểu diễn rõ **chưa xác định cước**, không đặt ngày giả

- **Tình huống:** Chưa có số container / ngày giao
- **Xử lý:** Để trống + nhãn “Chưa có số”/“Chưa chốt lịch”

- **Tình huống:** Cược: tiền về trước ngày nộp CV
- **Xử lý:** Chỉ nêu bất thường, **không chặn** (cần khách hàng xác nhận quy tắc)

- **Tình huống:** Chuyến ngoài chốt (chưa gắn công việc vận chuyển)
- **Xử lý:** Không vào tổng; hiện mục riêng chỉ đọc dưới Bảng 2.3 với nhãn **Ngoài chốt**; ẩn khi không có; màn chốt debit cũng loại + hiện dòng tổng tiền bị loại

- **Tình huống:** Dòng chi phí âm
- **Xử lý:** Hiện để đối soát nhưng **không cộng vào tổng nào**; màn nhập vẫn chặn số âm

- **Tình huống:** Xe nội bộ có mã đối chiếu trong báo cáo phải trả
- **Xử lý:** Vẫn **loại xe nội bộ**, không biến xe nhà thành xe ngoài, không tạo nhà cung cấp công nợ mới

- **Tình huống:** Gõ text vào ô tìm kiếm/thiếu lựa chọn
- **Xử lý:** Text chỉ đi qua, **không** tự nhận làm lựa chọn rồi đóng menu

- **Tình huống:** Lô LCL ở Tổng quan nhưng mất ở Chi tiết
- **Xử lý:** Lỗi dữ liệu phải sửa, không chấp nhận trạng thái hai màn hình lệch nhau [LCL-01]

- **Tình huống:** “Số yêu cầu chờ duyệt” trên tổng quan Ops
- **Xử lý:** **Chưa chốt:** mâu thuẫn với nguyên tắc không phê duyệt — cần xác định dữ liệu đếm""",
"""- **Giá dầu kỳ < giá mốc:** phụ phí dầu = 0 — đây là 0 thật, hợp lệ, khác với thiếu tham số; phải nói rõ, không tự gán 0.
- **Mở kỳ giá dầu mới:** không đổi cước đã phát hành; lô phát sinh trong lúc chờ “Để sau” giữ giá cũ.
- **Thiếu giá gốc 15T / thiếu lag / ngưỡng / kỳ giá:** báo thiếu đúng phần; không dùng 0, số minh hoạ hay giá của tuyến/loại xe khác.
- **Chưa có Ngày vận chuyển:** vẫn lưu được thông tin lô; biểu diễn rõ **chưa xác định cước**, không đặt ngày giả.
- **Chưa có số container / ngày giao:** để trống kèm nhãn “Chưa có số”/“Chưa chốt lịch”.
- **Cược: tiền về trước ngày nộp CV:** chỉ nêu bất thường, **không chặn** (cần khách hàng xác nhận quy tắc).
- **Chuyến ngoài chốt (chưa gắn công việc vận chuyển):** không vào tổng; hiện mục riêng chỉ đọc dưới Bảng 2.3 với nhãn **Ngoài chốt**, ẩn khi không có; màn chốt debit cũng loại và hiện dòng tổng tiền bị loại.
- **Dòng chi phí âm:** hiện để đối soát nhưng **không cộng vào tổng nào**; màn nhập vẫn chặn số âm.
- **Xe nội bộ có mã đối chiếu trong báo cáo phải trả:** vẫn tính là **xe nội bộ** — không biến xe nhà thành xe ngoài, không tạo nhà cung cấp công nợ mới.
- **Gõ text vào ô tìm kiếm khi chưa có lựa chọn:** text chỉ đi qua, **không** tự nhận làm lựa chọn rồi đóng menu.
- **Lô LCL hiện ở Tổng quan nhưng mất ở Chi tiết:** đây là lỗi dữ liệu phải sửa; không chấp nhận trạng thái hai màn hình lệch nhau [LCL-01].
- **“Số yêu cầu chờ duyệt” trên tổng quan Ops:** **chưa chốt** — mâu thuẫn với nguyên tắc không phê duyệt; cần xác định dữ liệu đếm."""))

# ---- Block 13: §2.7 điểm còn mở ----------------------------------------------
P.append((
"""- **#:** 1
- **Điểm còn mở:** **Bộ chứng từ LCL** thay phiếu hạ container
- **Ghi chú:** Chưa chốt với người phụ trách nghiệp vụ

- **#:** 2
- **Điểm còn mở:** **Thời điểm ghi công nợ phải trả (AP)** trên chuỗi debit vendor
- **Ghi chú:** Giữ quy tắc hiện hành đến khi khách hàng xác nhận

- **#:** 3
- **Điểm còn mở:** **Cảnh báo quá hạn cược container**: mốc bắt đầu, số ngày, cách nhắc
- **Ghi chú:** Hiện chỉ có 2 cảnh báo 7 ngày/tổng chưa hoàn

- **#:** 4
- **Điểm còn mở:** **Debit tab + xuất biểu mẫu** trong màn chốt debit
- **Ghi chú:** Để lại chờ bản đặc tả hoàn chỉnh của khách hàng

- **#:** 5
- **Điểm còn mở:** **Điều kiện hợp đồng / nguồn thông tin** chưa xác định
- **Ghi chú:** Cần chốt trước khi áp dụng; không tự đặt giá, giấy tờ mới hay thêm phê duyệt

- **#:** 6
- **Điểm còn mở:** **Mức giá và điều kiện cước cụ thể**
- **Ghi chú:** Nằm ở tài liệu cước chuyên ngành, không đặt lại ở quy trình

- **#:** 7
- **Điểm còn mở:** **Quy tắc “phải nộp chứng từ hoàn cược trước khi nhận tiền”**
- **Ghi chú:** Cần khách hàng xác nhận, không tự chặn

- **#:** 8
- **Điểm còn mở:** **Số tiền âm của dòng chi phí ngoài màn Ops/lái xe/kế toán**
- **Ghi chú:** Luật tổng đã chốt nhưng màn hình nhập vẫn chặn số âm “cho tới khi có quyết định riêng”

- **#:** 9
- **Điểm còn mở:** **Thu hồi phân công xe với lô đã có khoản chi đã lưu**
- **Ghi chú:** Tài liệu nêu “chỉ thu hồi quyền trên lô chưa có khoản chi”; hành vi với lô đã có khoản chi chưa rõ

- **#:** 10
- **Điểm còn mở:** **Bảng giá nâng/hạ**
- **Ghi chú:** Ops dùng số thực chi, không tự áp định mức — bảng định mức này tồn tại ở đâu, ai dùng chưa mô tả

- **#:** 11
- **Điểm còn mở:** **Loại chứng từ bắt buộc theo từng loại phí**
- **Ghi chú:** Chỉ có cờ nhóm “yêu cầu hóa đơn” vs “không hóa đơn”; danh sách cụ thể chưa có

- **#:** 12
- **Điểm còn mở:** **Tiêu chí bằng chứng thay thế** khi phê duyệt
- **Ghi chú:** 4 loại được “cân nhắc” nhưng tiêu chí chấp nhận/từ chối chưa định nghĩa

- **#:** 13
- **Điểm còn mở:** **“Số yêu cầu chờ duyệt”** trên trang tổng quan Ops
- **Ghi chú:** Mâu thuẫn với nguyên tắc không phê duyệt

- **#:** 14
- **Điểm còn mở:** **Điều chỉnh quỹ “có căn cứ”**
- **Ghi chú:** Ai ghi, căn cứ nào, có cần duyệt không, bảng nào hiển thị?

- **#:** 15
- **Điểm còn mở:** **Quyền “người có quyền tài chính”** ở mức chi tiết
- **Ghi chú:** Danh sách quyền chi tiết chưa định nghĩa

- **#:** 16
- **Điểm còn mở:** **Kỳ kế toán** (chu kỳ, thời điểm khóa, quyền khi khóa)
- **Ghi chú:** Chỉ được nhắc đến, chưa định nghĩa — thuộc phân hệ kế toán

- **#:** 17
- **Điểm còn mở:** **Trạng thái “đã gửi kế toán” của khoản chi**
- **Ghi chú:** Được nhắc trong quyết định ngày 21/10 nhưng không có trong bảng trạng thái

- **#:** 18
- **Điểm còn mở:** **Danh sách trạng thái cấp lô đầy đủ** (§2.3.2)
- **Ghi chú:** Cần đối chiếu, rà soát đầy đủ trước khi đóng đặc tả

- **#:** 19
- **Điểm còn mở:** **Cách mở lại khi tick nhầm “đã hoàn cược”** và ngày tiền đổ về quỹ ACB
- **Ghi chú:** Chỉ ghi “tick lại bị chặn”

- **#:** 20
- **Điểm còn mở:** **Định mức tiền đường theo tuyến** (“để trống, khách bổ sung sau”)
- **Ghi chú:** Cơ chế nhập/bổ sung sau chưa mô tả

- **#:** 21
- **Điểm còn mở:** **Mapping danh mục ↔ nhóm quyết toán ↔ cờ hóa đơn** chính xác
- **Ghi chú:** Đặc biệt nhóm “Phí khác (không hóa đơn)”""",
"""1. **Bộ chứng từ LCL** thay phiếu hạ container — chưa chốt với người phụ trách nghiệp vụ.
2. **Thời điểm ghi công nợ phải trả (AP)** trên chuỗi debit vendor — giữ quy tắc hiện hành đến khi khách hàng xác nhận.
3. **Cảnh báo quá hạn cược container** (mốc bắt đầu, số ngày, cách nhắc) — hiện chỉ có 2 cảnh báo 7 ngày/tổng chưa hoàn.
4. **Debit tab + xuất biểu mẫu** trong màn chốt debit — để lại chờ bản đặc tả hoàn chỉnh của khách hàng.
5. **Điều kiện hợp đồng / nguồn thông tin** chưa xác định — cần chốt trước khi áp dụng; không tự đặt giá, giấy tờ mới hay thêm phê duyệt.
6. **Mức giá và điều kiện cước cụ thể** — nằm ở tài liệu cước chuyên ngành, không đặt lại ở quy trình.
7. **Quy tắc “phải nộp chứng từ hoàn cược trước khi nhận tiền”** — cần khách hàng xác nhận, không tự chặn.
8. **Số tiền âm của dòng chi phí ngoài màn Ops/lái xe/kế toán** — luật tổng đã chốt nhưng màn hình nhập vẫn chặn số âm “cho tới khi có quyết định riêng”.
9. **Thu hồi phân công xe với lô đã có khoản chi đã lưu** — tài liệu nêu “chỉ thu hồi quyền trên lô chưa có khoản chi”; hành vi với lô đã có khoản chi chưa rõ.
10. **Bảng giá nâng/hạ** — Ops dùng số thực chi, không tự áp định mức; bảng định mức này tồn tại ở đâu, ai dùng chưa được mô tả.
11. **Loại chứng từ bắt buộc theo từng loại phí** — chỉ có cờ nhóm “yêu cầu hóa đơn” vs “không hóa đơn”; danh sách cụ thể chưa có.
12. **Tiêu chí bằng chứng thay thế** khi phê duyệt — 4 loại được “cân nhắc” nhưng tiêu chí chấp nhận/từ chối chưa định nghĩa.
13. **“Số yêu cầu chờ duyệt”** trên trang tổng quan Ops — mâu thuẫn với nguyên tắc không phê duyệt.
14. **Điều chỉnh quỹ “có căn cứ”** — ai ghi, căn cứ nào, có cần duyệt không, bảng nào hiển thị?
15. **Quyền “người có quyền tài chính”** ở mức chi tiết — danh sách quyền chi tiết chưa định nghĩa.
16. **Kỳ kế toán** (chu kỳ, thời điểm khóa, quyền khi khóa) — chỉ được nhắc đến, chưa định nghĩa; thuộc phân hệ kế toán.
17. **Trạng thái “đã gửi kế toán” của khoản chi** — được nhắc trong quyết định ngày 21/10 nhưng không có trong bảng trạng thái.
18. **Danh sách trạng thái cấp lô đầy đủ** (§2.3.2) — cần đối chiếu, rà soát đầy đủ trước khi đóng đặc tả.
19. **Cách mở lại khi tick nhầm “đã hoàn cược”** và ngày tiền đổ về quỹ ACB — hiện chỉ ghi “tick lại bị chặn”.
20. **Định mức tiền đường theo tuyến** (“để trống, khách bổ sung sau”) — cơ chế nhập/bổ sung sau chưa mô tả.
21. **Mapping danh mục ↔ nhóm quyết toán ↔ cờ hóa đơn** chính xác — đặc biệt nhóm “Phí khác (không hóa đơn)”."""))

ok = True
for i, (old, new) in enumerate(P):
    n = src.count(old)
    if n != 1:
        print(f"BLOCK B{i+1}: found {n} times — ABORT")
        ok = False
if not ok:
    sys.exit(1)
for i, (old, new) in enumerate(P):
    src = src.replace(old, new)
    print(f"block B{i+1} replaced")

open("after/spec-2.md", "w").write(src)
print("written", len(src))
