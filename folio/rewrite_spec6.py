#!/usr/bin/env python3
src = open("src/spec-6.md").read()

def cut(start_marker, end_marker):
    i = src.index(start_marker)
    j = src.index(end_marker, i)
    return src[i:j]

P = []

# B1: surface/work pairs
old = cut("- **Bề mặt:** Bảng tổng quan tiền", "\n\n**Bốn danh mục.**")
new = """- Trên **Bảng tổng quan tiền**, kế toán theo dõi phải thu/phải trả, cược, quỹ và các cảnh báo nợ.
- Tại **Kiểm soát phơi phiếu**, kế toán duyệt chi phí, thêm khoản chi và lập phiếu thu/chi.
- Qua **Kế hoạch điều động → Chốt debit**, kế toán lập công nợ và xuất Debit Note.
- Trên **Sổ quỹ / công nợ**, kế toán ghi thu và phân bổ nguồn.
- Ở **Tạm ứng / hoàn ứng**, kế toán duyệt chi phí Ops và lập phiếu hoàn ứng.
- Với **Chấm công / lương / nhân sự**, kế toán xem và chốt trong phạm vi quyền."""
P.append((old, new))

# B2: fund source mapping
old = cut("- **Dòng chi:** Chi hộ **có hóa đơn**", "\n\nChọn sai → phiếu")
new = """- Dòng chi thuộc chi hộ **có hóa đơn** (kể cả chi phí hóa đơn) thì ghi vào **Quỹ tiền mặt**.
- Dòng chi là ứng Ops, chi phí lô **không hóa đơn**, phát sinh Ops, tiền đường hay cược container thì ghi vào **Quỹ công ty**."""
P.append((old, new))

# B3: data model
old = cut("- **Thực thể (bảng/màn):** Lô/Phơi phiếu (Bảng 1.1.1)", "\n\n## 6.6 Báo cáo")
new = """- **Lô/Phơi phiếu (Bảng 1.1.1)** có các trường chính: mã lô, lịch trình, khách hàng (+nhà máy), số container, loại cont, xuất/nhập, trọng tải, nâng (địa điểm/đơn giá), hạ, cước thu (tự động), Lạch Huyện (tự động), phụ phí (tự động), phát sinh (CUS), cước trả ĐV, phát sinh DV, phí RU, tiền đường, tiền nâng, tiền hạ, PS khác, ngày, trạng thái nhận phơi (đã/chưa + ngày tích), ghi chú vận tải, ghi chú lái xe, hình thức phơi, phân xe (nhà xe + BKS), cờ xe nhà/xe ngoài.
- **Chi phí dòng (phiếu nhập + bảng duyệt)** có trường chính: nhóm chi phí (Tiền đường — danh sách trường trong bản gốc bị cắt dở).
- **Hóa đơn kết hợp (Bảng 1.1.2)** có các trường chính: ngày, lô (khách/nhà máy), số cont, loại cont, xuất/nhập, MST, nhà cung cấp, số tiền, số hóa đơn, số tiền trả bên cung cấp HĐ, số tiền trừ cho khách (nếu có), chênh lệch, ghi chú, tiến độ hóa đơn (đã gửi / chưa gửi / Gửi hóa đơn + "chọn nâng/hạ" — mỗi lô theo dõi theo chiều nâng hoặc hạ).
- **Cược (Bảng 1.1.3)** có các trường chính: ngày cược, khách hàng, hãng tàu, bill, số tiền cược, ngày nộp CV, ngày dự kiến hoàn cược (= CV + 14), trạng thái hoàn cược (3 mức), ghi chú, cờ "có cược".
- **Tạm ứng/hoàn ứng (Bảng 1.1.4)** có các trường chính: ngày lập, ngày duyệt DNTT, nhân viên, lô (khách/nhà máy, hàng hóa), phí chi hộ không hóa đơn (tên phí, phí giao nhận, phí phát sinh), phí chi hộ có hóa đơn (tên phí, số HĐ), ghi chi, ĐNTT, đã ứng, còn phải hoàn ứng, đợt đối soát.
- **Công nợ (1.2.1 + 1.4.x)** có các trường chính: kỳ (từ/đến), lần, tháng, chiều (thu/trả), VAT%, số tiền VAT, tổng; đối tác (khách/nhà xe) với cước thu / cước trả / tổng.
- **Quỹ** gồm **4 thực thể tiền**: quỹ tiền mặt, quỹ công ty, quỹ/tài khoản **ACB** (chuyên hoàn cược), **TK OPS** (tạm ứng) — bảng tổng quan tiền đọc tổng 2 quỹ.
- **Sổ quỹ (giao dịch)** có các trường: Số phiếu, Ngày, Đối tượng, Mô tả, Tài khoản, Thu/Chi, Số dư (kèm nhãn tổng số dư và trạng thái "số dư ghi sổ").
- **Chi phí ghi nhận** có các trường: Ngày phát sinh (bắt buộc), Nhà cung cấp (bắt buộc), Hạng mục (bắt buộc), Loại chi phí, Số tiền (bắt buộc), Mã biên lai, Ghi chú, ảnh hóa đơn/chứng từ.
- **Công nợ khách hàng** gồm thẻ Tổng công nợ phải thu / Số khách hàng / Số khách quá hạn; dòng khách hàng có tên, tổng công nợ, tiền quá hạn, ngày thanh toán gần nhất.
- **Lương & chấm công** có các trường: tháng/năm, Tổng quỹ lương, số lái xe, số đã xác nhận, ngày đi chuyến, ngày chờ việc, hình thức lương từng lái xe (chuyến/tháng), bảng lương + cấu thành.
- **Nhà cung cấp** có các trường: tên, tên rút gọn, mã, mã số thuế, liên hệ, SĐT, công nợ.
- **Nhân sự** có các trường: nhân viên, đơn vị phụ trách/bộ phận (cần tách văn phòng/lái xe), bảng chấm công, bảng lương."""
P.append((old, new))

# B4: reports
old = cut("- **Báo cáo / màn:** Bảng tổng quan tiền", "\n\n## 6.7 Edge cases")
new = """- **Bảng tổng quan tiền**: AC-KT-01…05 (2 thẻ hạn nợ, biểu đồ cược tuần, thông báo Quỹ, cảnh báo nợ 4 nhóm, Quỹ âm) — chi tiết ở 6.1.
- **Bảng 1.1.1 tổng hợp phơi phiếu**: nút **TỔNG CON (cột F) kiểu bảng tính**; phân rã tổng theo người chi.
- **Bảng 1.1.2 hóa đơn kết hợp**: 4 ô Tổng (cont, tiền, thu, chi) + tiến độ hóa đơn.
- **Bảng 1.1.3 hoàn cược**: ô Tổng + bộ lọc trạng thái; 2 cảnh báo song song.
- **Bảng 1.1.4 + báo cáo tổng hợp hoàn ứng**: 3 thẻ *Tổng ĐNTT · Tổng đã ứng · Tổng còn phải hoàn ứng* (hoặc 6 cột STT…Còn phải hoàn ứng), lọc theo đợt đối soát, kèm nhãn chiều số.
- **BÁO CÁO THU/TRẢ PHƠI**: Phải thu theo khách / Phải trả theo nhà xe, **ẩn dư 0** (AC-KT-15), lọc theo khoảng ngày; chọn tên nhà xe → hiện chi phí còn thiếu.
- **Chi tiết phải thu/trả + tổng hợp công nợ tháng**: lọc Từ–Đến ngày, tổng hợp sản lượng các bên để đối soát cuối tháng; **tổng hợp = tổng tiền + VAT**.
- **Báo cáo lãi lỗ**: 4 thẻ *Tổng doanh thu · Tổng chi phí · Lãi gộp · Biên lợi nhuận*; biểu đồ doanh thu & lãi gộp theo tháng + cơ cấu chi phí; bảng **Top xe theo lợi nhuận**; bảng chi tiết lãi lỗ theo từng tháng; nút Xuất bảng tính; kỳ mặc định là tháng hiện tại, đổi bằng bộ lọc thời gian — **màn này chỉ có ở hướng dẫn, bản đặc tả không mô tả quy tắc tính doanh thu/chi phí** → **Chưa chốt**.
- **Năng suất đội xe**: tab *Toàn đội trong 1 ngày* gồm 6 chỉ số tổng hợp + bảng chi tiết từng xe; tab *Từng xe trong 1 tháng* gồm sản lượng, số xe hoạt động, % năng suất bình quân; xuất bảng tính ở tab tháng; số liệu lấy từ chuyến hoàn thành trong kỳ.
- **Lương & chấm công / Tổng hợp xếp lệnh**: màn Lương & chấm công (thẻ tổng hợp + bảng lương + Chốt kỳ lương); báo cáo bảng tính tổng hợp xếp lệnh tháng theo ký hiệu K/Q/Đ/L/N/P.
- **Xuất bảng tính**: nút xuất + thông báo xác nhận ở báo cáo lãi lỗ, nhà cung cấp, năng suất tab tháng."""
P.append((old, new))

# B5: edge cases
old = cut("- **Tình huống:** Quỹ âm", "\n\n## 6.8 Các điểm còn mở")
new = """- **Quỹ âm**: cảnh báo **chỉ khi cả hai quỹ < 0** (AC-KT-05); một quỹ âm không kích hoạt cảnh báo — cách xử lý tiếp theo chưa có tài liệu → **Chưa chốt**.
- **Số âm hoàn ứng**: "Còn phải hoàn ứng" âm nghĩa là Ops ứng cao hơn làm hàng → cảnh báo thu tiền, **không hiện số âm trần** (đã chốt).
- **Số âm dòng chi phí**: dòng chi phí âm **không cộng vào bất kỳ tổng nào** (dòng vẫn hiện để đối soát); riêng Thực chi mới âm bị chặn — luật này **khác** luật phiếu hoàn ứng âm (chi tiết Chương 2 §2.4.5).
- **Dư 0**: khách có còn phải thu = 0 bị **ẩn mặc định** (AC-KT-15) — có cần nút bật hiện lại hay không **chưa chốt**.
- **Chưa xác định**: đây là dòng gộp các khoản không rõ đối tượng; thiếu dữ liệu Debit thì hiển thị nhãn **"Thiếu …"**, không gán 0.
- **Xe nhà vs xe ngoài**: hai luồng duyệt chi phí khác nhau (AC-KT-06).
- **Nhập trùng Ops**: hệ thống báo trùng và hiện hộp thoại xác nhận "ĐÃ ĐƯỢC ID…. NHẬP TRƯỚC ĐÓ, BẠN VẪN TIẾP TỤC NHẬP CHỨ"; dòng đã hủy không cảnh báo.
- **Chờ điều chỉnh cước**: chặn xuất Debit của dòng đó (AC-KT-13).
- **Hãng tàu hoàn cược lâu hơn 14 ngày**: sửa tay ngày dự kiến, hệ thống không tự chặn.
- **Cảnh báo cược +7 ngày**: đếm theo bộ lọc (có ngày nộp CV + chưa hoàn cược); tắt được trong phiên.
- **Ảnh/chứng từ**: Ops **có thể chụp hoặc không, không bị ghi nhận thiếu chứng từ** (Ops in hóa đơn đặt bàn kế toán đối soát).
- **Hai dòng gộp đặc biệt**: "Chưa xác định" + "XE NHÀ – SILVER SEA" trong báo cáo thu/trả phơi.
- **Đơn vị phụ trách**: hiện là bộ phận nhân sự; yêu cầu tách văn phòng/lái xe chưa làm."""
P.append((old, new))

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
open("after/spec-6.md", "w").write(src)
print("written", len(src))
