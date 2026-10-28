#!/usr/bin/env python3
# Rewrite spec-2 field:value blocks into prose. Exact-match replacements.
import sys

src = open("src/spec-2.md").read()

P = []

# ---- Block 1: §2.1 step outputs --------------------------------------------
P.append((
"""- **Bước:** 3
- **Sự kiện được ghi nhận:** Mã lô tồn tại
- **— không suy diễn thêm.** Chưa đủ dữ liệu điều xe

- **Bước:** 4
- **Sự kiện được ghi nhận:** Đã phát lệnh
- **— không suy diễn thêm.** Lái xe đã nhận; xe đã xuất phát

- **Bước:** 5
- **Sự kiện được ghi nhận:** Hoàn thành vận chuyển
- **— không suy diễn thêm.** Đủ chứng từ; đã lập bảng kê

- **Bước:** 6
- **Sự kiện được ghi nhận:** Đã nhận chứng từ giấy (người + ngày)
- **— không suy diễn thêm.** Đã thanh toán

- **Bước:** 7
- **Sự kiện được ghi nhận:** Cước đã khóa / chi phí đã ghi
- **— không suy diễn thêm.** Tiền đã thu

- **Bước:** 8
- **Sự kiện được ghi nhận:** Phiếu thu/chi đã ghi, phân bổ đã ghi
- **— không suy diễn thêm.** Chuyển khoản thực tế đã xảy ra

- **Bước:** 9
- **Sự kiện được ghi nhận:** Kỳ đã khóa
- **— không suy diễn thêm.** — (không mở lại tự động)""",
"""- Ở bước 3, sự kiện được ghi nhận là **mã lô tồn tại** — và chỉ vậy thôi: chưa thể suy ra lô đã đủ dữ liệu điều xe.
- Ở bước 4, sự kiện được ghi nhận là **đã phát lệnh** — chưa thể suy ra lái xe đã nhận hay xe đã xuất phát.
- Ở bước 5, sự kiện được ghi nhận là **hoàn thành vận chuyển** — chưa thể suy ra đã đủ chứng từ hay đã lập bảng kê.
- Ở bước 6, sự kiện được ghi nhận là **đã nhận chứng từ giấy (kèm người và ngày nhận)** — chưa thể suy ra đã thanh toán.
- Ở bước 7, sự kiện được ghi nhận là **cước đã khóa / chi phí đã ghi** — chưa thể suy ra tiền đã thu.
- Ở bước 8, sự kiện được ghi nhận là **phiếu thu/chi đã ghi, phân bổ đã ghi** — chưa thể suy ra chuyển khoản thực tế đã xảy ra.
- Ở bước 9, sự kiện được ghi nhận là **kỳ đã khóa** — ngoài ra không suy diễn gì thêm, và kỳ khóa không tự mở lại."""))

# ---- Block 2: §2.2.4 Đơn/Kẹp/Kết hợp ---------------------------------------
P.append((
"""- **Tiêu chí:** Công việc
- **Đơn:** 1 phần việc
- **Kẹp:** 2 container 20FT đồng thời
- **Kết hợp:** 2 phần việc nối tiếp, tái dùng vỏ

- **Tiêu chí:** Theo dõi
- **Đơn:** 1 lệnh
- **Kẹp:** 2 lệnh riêng, quan hệ cặp
- **Kết hợp:** 2 lệnh riêng, có thứ tự

- **Tiêu chí:** Nguồn lực
- **Đơn:** Xe phù hợp
- **Kẹp:** Cùng xe + moóc + tài xế
- **Kết hợp:** Cùng xe/tài xế + vỏ phù hợp

- **Tiêu chí:** Lịch
- **Đơn:** Thực hiện được
- **Kẹp:** Đồng thời trong cặp hợp lệ
- **Kết hợp:** Đủ thời gian chuyển tiếp

- **Tiêu chí:** Phí chung
- **Đơn:** Theo định mức
- **Kẹp:** **Không nhân đôi** phí đường/VETC
- **Kết hợp:** Không nhân đôi phí chung vòng

- **Tiêu chí:** Thu nhập lái xe
- **Đơn:** Theo công việc
- **Kẹp:** Cuốc cơ bản + phụ phí kẹp
- **Kết hợp:** Cuốc cơ bản + phụ phí kết hợp""",
"""- Về phạm vi công việc: Đơn gồm 1 phần việc; Kẹp gồm 2 container 20FT đi đồng thời; Kết hợp gồm 2 phần việc nối tiếp, tái dùng vỏ.
- Về cách theo dõi: Đơn là 1 lệnh; Kẹp là 2 lệnh riêng có quan hệ cặp; Kết hợp là 2 lệnh riêng có thứ tự.
- Về nguồn lực: Đơn chỉ cần xe phù hợp; Kẹp dùng cùng xe + moóc + tài xế; Kết hợp dùng cùng xe/tài xế và vỏ container phù hợp.
- Về lịch: Đơn chỉ cần lịch thực hiện được; Kẹp phải đồng thời trong một cặp hợp lệ; Kết hợp phải đủ thời gian chuyển tiếp giữa hai lệnh.
- Về phí chung: Đơn tính theo định mức; Kẹp **không nhân đôi** phí đường/VETC; Kết hợp không nhân đôi phí chung theo vòng.
- Về thu nhập lái xe: Đơn tính theo công việc; Kẹp là cuốc cơ bản + phụ phí kẹp; Kết hợp là cuốc cơ bản + phụ phí kết hợp."""))

# ---- Block 3: §2.3.1 giai đoạn phần việc ------------------------------------
P.append((
"""- **#:** 0
- - **Điều kiện vào:** Lô mới tạo hoặc thiếu lịch/số lượng/phân bổ
- **Luật chuyển:** Bổ sung đủ dữ liệu → 1
- **Tác dụng phụ / điều cấm:** Vẫn lưu và tra cứu được; không tự gán ngày giả

- **#:** 1
- - **Điều kiện vào:** Đủ dữ liệu điều xe; lô tự xuất hiện kế hoạch ĐV
- **Luật chuyển:** Điều vận phân bổ + phát lệnh → 2
- **Tác dụng phụ / điều cấm:** Chưa có lệnh thì chưa có gì để lái xe nhận

- **#:** 2
- - **Điều kiện vào:** Điều kiện phát lệnh thỏa; phát lệnh thành công
- **Luật chuyển:** Lái xe nhận lệnh (chủ động, thành công) → 3
- **Tác dụng phụ / điều cấm:** **“Đã phát lệnh” ≠ “đã nhận”**; không suy ra xe đã xuất phát

- **#:** 3
- - **Điều kiện vào:** Lái xe chủ động nhận khi còn được giao việc + có Internet
- **Luật chuyển:** Ghi tiến độ đến hết → 4; hoặc hủy → 5
- **Tác dụng phụ / điều cấm:** Giờ nhận ≠ giờ xuất phát; chuyển trạng thái **chỉ khi thành công**

- **#:** 4
- - **Điều kiện vào:** Đủ điều kiện hoàn thành (§2.2.5)
- **Luật chuyển:** — (trạng thái cuối của phần việc còn hiệu lực)
- **Tác dụng phụ / điều cấm:** Một container hoàn thành **không** làm cả lô hoàn thành

- **#:** 5
- - **Điều kiện vào:** Có quyết định hủy hợp lệ
- **Tác dụng phụ / điều cấm:** **Có lý do + lịch sử**; **không tính là đã giao**""",
"""- **Giai đoạn 0** — lô mới tạo hoặc còn thiếu lịch/số lượng/phân bổ. Bổ sung đủ dữ liệu sẽ chuyển sang giai đoạn 1. Ở giai đoạn này lô vẫn lưu và tra cứu được, nhưng không được tự gán ngày giả.
- **Giai đoạn 1** — lô đã đủ dữ liệu điều xe và tự xuất hiện trong kế hoạch Điều vận. Khi Điều vận phân bổ và phát lệnh, lô chuyển sang giai đoạn 2. Chưa phát lệnh thì chưa có gì cho lái xe nhận.
- **Giai đoạn 2** — điều kiện phát lệnh đã thỏa và phát lệnh thành công. Lái xe chủ động nhận lệnh (và phải thành công) sẽ chuyển sang giai đoạn 3. Lưu ý **“đã phát lệnh” ≠ “đã nhận”**, và không được suy ra xe đã xuất phát.
- **Giai đoạn 3** — lái xe đã chủ động nhận khi còn được giao việc và có Internet. Ghi tiến độ đến hết sẽ chuyển sang giai đoạn 4; nếu hủy thì chuyển sang giai đoạn 5. Giờ nhận ≠ giờ xuất phát, và trạng thái chỉ chuyển khi thao tác **thành công**.
- **Giai đoạn 4** — đã đủ điều kiện hoàn thành (§2.2.5); đây là trạng thái cuối của phần việc còn hiệu lực. Một container hoàn thành **không** làm cả lô hoàn thành.
- **Giai đoạn 5** — vào đây khi có quyết định hủy hợp lệ. Phải có **lý do + lịch sử**, và hủy **không tính là đã giao**."""))

# ---- Block 4: §2.3.2 trạng thái cấp lô --------------------------------------
P.append((
"""- **Trạng thái lô:** **DRAFT** (nháp)
- **Ý nghĩa:** Trạng thái ban đầu khi tạo lô; không có bước nộp
- **Ghi chú:** Quyết định ngày 2026-10-01

- **Trạng thái lô:** **Chưa chốt lịch**
- **Ý nghĩa:** Chưa có ngày giao/hẹn; vẫn lưu và tìm lại được trong nhóm riêng

- **Trạng thái lô:** **Chờ điều xe**
- **Ý nghĩa:** Đủ dữ liệu, chưa phát lệnh
- **Ghi chú:** chip Tổng quan lô CUS

- **Trạng thái lô:** **Chờ đối soát**
- **Ý nghĩa:** Chưa hoàn tất đối soát phía Kế toán
- **Ghi chú:** chip Tổng quan lô CUS

- **Trạng thái lô:** **Đã phát lệnh / đang vận chuyển**
- **Ý nghĩa:** Có lệnh và/hoặc đang thực hiện

- **Trạng thái lô:** **Hoàn thành**
- **Ý nghĩa:** Mọi phần việc bắt buộc xong; vẫn tra cứu được

- **Trạng thái lô:** **Đã hủy**
- **Ý nghĩa:** Có lý do + lịch sử; tách khỏi việc đang làm nhưng tra cứu được

- **Trạng thái lô:** **Đã khóa kế toán**
- **Ý nghĩa:** Snapshot chi phí/cước đóng băng; chặn sửa chi phí, tờ khai

- **Trạng thái lô:** **Đã thuộc một bảng kê**
- **Ý nghĩa:** Chọn lại lô vào bảng kê khác bị chặn + nêu số lô""",
"""- **DRAFT (nháp)** là trạng thái ban đầu khi tạo lô; không có bước nộp (quyết định ngày 2026-10-01).
- **Chưa chốt lịch** nghĩa là lô chưa có ngày giao/hẹn; lô vẫn lưu và tìm lại được trong nhóm riêng.
- **Chờ điều xe** nghĩa là lô đã đủ dữ liệu nhưng chưa phát lệnh (hiện trên chip Tổng quan lô của CUS).
- **Chờ đối soát** nghĩa là lô chưa hoàn tất đối soát phía Kế toán (hiện trên chip Tổng quan lô của CUS).
- **Đã phát lệnh / đang vận chuyển** nghĩa là lô đã có lệnh và/hoặc đang được thực hiện.
- **Hoàn thành** nghĩa là mọi phần việc bắt buộc đã xong; lô vẫn tra cứu được.
- **Đã hủy** nghĩa là lô có lý do + lịch sử, được tách khỏi việc đang làm nhưng vẫn tra cứu được.
- **Đã khóa kế toán** nghĩa là bản chụp chi phí/cước đã đóng băng; hệ thống chặn sửa chi phí và tờ khai.
- **Đã thuộc một bảng kê** nghĩa là việc chọn lại lô vào bảng kê khác bị chặn kèm thông báo số lô."""))

# ---- Block 5: §2.3.3 trạng thái xe/máy --------------------------------------
P.append((
"""- **Mã:** 0
- - **Định nghĩa:** Xe chưa có công việc phù hợp đang thực hiện
- **Hành vi khi thiếu dữ liệu:** Chưa có xe được giao → giải thích rõ + hướng tới người quản lý phân công, không hiện bảng trống

- **Mã:** 1
- - **Định nghĩa:** Đã phát lệnh nhưng lái xe chưa nhận thực tế

- **Mã:** 2
- - **Định nghĩa:** Lái xe đã nhận + có tiến độ ghi nhận

- **Mã:** 3
- - **Định nghĩa:** Công việc kết thúc, vẫn tra cứu được

- **Mã:** 4
- - **Định nghĩa:** Chưa lấy được thông tin mới
- **Hành vi khi thiếu dữ liệu:** Hiển thị **thời điểm** của thông tin đang xem""",
"""- **Mức 0** — xe chưa có công việc phù hợp đang thực hiện. Khi chưa có xe nào được giao, màn hình giải thích rõ và hướng tới người quản lý phân công thay vì hiện bảng trống.
- **Mức 1** — đã phát lệnh nhưng lái xe chưa nhận thực tế.
- **Mức 2** — lái xe đã nhận và đã có tiến độ được ghi nhận.
- **Mức 3** — công việc đã kết thúc nhưng vẫn tra cứu được.
- **Mức 4** — chưa lấy được thông tin mới; màn hình hiển thị **thời điểm** của thông tin đang xem."""))

# ---- Block 6: §2.3.4 nhóm trạng thái ----------------------------------------
P.append((
"""- **Nhóm:** **Nhập liệu**
- **Các trạng thái:** đang nhập · đang lưu · đã lưu · chưa lưu được · chưa rõ kết quả
- **Ghi chú:** Phân biệt “đã ghi” với “đang lưu”

- **Nhóm:** **Khoản chi**
- **Các trạng thái:** đã ghi nhận · đã điều chỉnh · đã hủy (có lý do)
- **Ghi chú:** Hủy có dấu vết, không xóa âm thầm

- **Nhóm:** **Chứng từ**
- **Các trạng thái:** còn thiếu · đang bổ sung · đã đủ · chưa đọc được
- **Ghi chú:** Tách khỏi “vận chuyển hoàn thành”

- **Nhóm:** **Bằng chứng / vận chuyển**
- **Các trạng thái:** đủ bằng chứng · vận chuyển hoàn thành · đã nhận chứng từ giấy
- **Ghi chú:** Ba thông tin riêng, không duyệt/từ chối nội bộ

- **Nhóm:** **Quyết toán**
- **Các trạng thái:** chưa quyết toán · đã quyết toán · có điều chỉnh
- **Ghi chú:** Quyết toán ≠ thanh toán

- **Nhóm:** **Kỳ kế toán**
- **Các trạng thái:** đang mở · đã khóa (+ thao tác còn được phép)
- **Ghi chú:** Không tự mở kỳ

- **Nhóm:** **Bảng kê**
- **Các trạng thái:** đủ dữ liệu → lập trực tiếp; thiếu → nêu từng lý do
- **Ghi chú:** Không hàng đợi duyệt

- **Nhóm:** **Phiếu/quỹ**
- **Các trạng thái:** trạng thái từng dòng (đã đổi/đã thanh toán/khóa kỳ) quyết định cả phiếu
- **Ghi chú:** Một dòng hỏng → cả phiếu không ghi

- **Nhóm:** **Đợt chốt debit**
- **Các trạng thái:** lô → 1 đợt · đang chờ điều chỉnh cước · đã khóa số liệu
- **Ghi chú:** Xem §2.2.9""",
"""- **Nhập liệu** gồm: đang nhập · đang lưu · đã lưu · chưa lưu được · chưa rõ kết quả — cần phân biệt “đã ghi” với “đang lưu”.
- **Khoản chi** gồm: đã ghi nhận · đã điều chỉnh · đã hủy (có lý do) — việc hủy có dấu vết, không xóa âm thầm.
- **Chứng từ** gồm: còn thiếu · đang bổ sung · đã đủ · chưa đọc được — tách khỏi trạng thái “vận chuyển hoàn thành”.
- **Bằng chứng / vận chuyển** gồm: đủ bằng chứng · vận chuyển hoàn thành · đã nhận chứng từ giấy — ba thông tin riêng, không có duyệt/từ chối nội bộ.
- **Quyết toán** gồm: chưa quyết toán · đã quyết toán · có điều chỉnh — quyết toán ≠ thanh toán.
- **Kỳ kế toán** gồm: đang mở · đã khóa (kèm các thao tác còn được phép) — không tự mở kỳ.
- **Bảng kê**: đủ dữ liệu thì lập trực tiếp; thiếu thì nêu từng lý do — không có hàng đợi duyệt.
- **Phiếu/quỹ**: trạng thái từng dòng (đã đổi/đã thanh toán/khóa kỳ) quyết định cả phiếu — một dòng hỏng thì cả phiếu không ghi.
- **Đợt chốt debit**: lô thuộc 1 đợt · đang chờ điều chỉnh cước · đã khóa số liệu (xem §2.2.9)."""))

# ---- Block 7: §2.3.5 ranh giới sửa phân công --------------------------------
P.append((
"""- **Tình huống:** Chưa phát lệnh
- **Quy tắc:** Sửa kế hoạch theo quyền, số lượng, khả năng thực hiện

- **Tình huống:** Đã phát lệnh nhưng lái xe **chưa thực tế nhận** công việc hiện tại
- **Quy tắc:** Đổi được nhà vận tải, xe, tài xế, moóc hợp lệ. **Không khóa** chỉ vì nhãn tổng hợp “đang vận chuyển”

- **Tình huống:** Lái xe **đã nhận** công việc hiện tại
- **Quy tắc:** **Chỉ đổi phương tiện**: xe đầu kéo/moóc với xe nhà; nhà xe/biển số với xe ngoài — **giữ nguyên lái xe**. Đổi lái xe hoặc chuyển giữa xe nhà ↔ xe ngoài → **chặn + nêu lý do + hướng xử lý được phép** (không chuyển sang gửi yêu cầu duyệt)

- **Tình huống:** Đã hoàn thành, đã hủy, hoặc kỳ đã khóa
- **Quy tắc:** Không sửa phân công như kế hoạch mới; xử bằng nghiệp vụ điều chỉnh, giữ lý do + lịch sử

- **Tình huống:** Nhãn trạng thái mâu thuẫn với thông tin nhận lệnh
- **Quy tắc:** Nêu rõ vấn đề, xác định việc nhận của phân công hiện tại; **không** tự coi là chưa nhận chỉ vì nhãn""",
"""- **Chưa phát lệnh:** sửa kế hoạch theo quyền, số lượng và khả năng thực hiện.
- **Đã phát lệnh nhưng lái xe chưa thực tế nhận** công việc hiện tại: đổi được nhà vận tải, xe, tài xế, moóc hợp lệ — **không khóa** chỉ vì nhãn tổng hợp “đang vận chuyển”.
- **Lái xe đã nhận** công việc hiện tại: **chỉ đổi được phương tiện** — xe đầu kéo/moóc với xe nhà, nhà xe/biển số với xe ngoài — và **giữ nguyên lái xe**. Muốn đổi lái xe hoặc chuyển giữa xe nhà ↔ xe ngoài thì bị **chặn kèm nêu lý do và hướng xử lý được phép** (không chuyển sang gửi yêu cầu duyệt).
- **Đã hoàn thành, đã hủy, hoặc kỳ đã khóa:** không sửa phân công như kế hoạch mới; xử bằng nghiệp vụ điều chỉnh, giữ lý do + lịch sử.
- **Nhãn trạng thái mâu thuẫn với thông tin nhận lệnh:** nêu rõ vấn đề và xác định việc nhận của phân công hiện tại; **không** tự coi là chưa nhận chỉ vì nhãn."""))

# ---- Block 8: §2.4.1 quy tắc bắt buộc ---------------------------------------
P.append((
"""- **#:** 1
- **Quy tắc:** **KM luôn × 2 (khứ hồi)**, kể cả chuyến 1 chiều hoặc chiều về rỗng
- **Hệ quả:** Cước không phụ thuộc việc tận dụng xe/ghép chuyến; ghép/kết hợp **không** thay đổi cước hợp đồng của từng lệnh

- **#:** 2
- **Quy tắc:** **H không âm** — kẹp về 0 khi G < F
- **Hệ quả:** Dầu rẻ → cước = J; công ty không giảm cước. Đây là **0 thật**, khác với thiếu tham số

- **#:** 3
- **Quy tắc:** **% chia sẻ cộng vào giá gốc J**, không chỉ thu % của phụ phí dầu; % không phụ thuộc loại xe (thuộc tuyến)
- **Hệ quả:** Tỷ lệ chia sẻ thuộc **cặp khách hàng–tuyến**

- **#:** 4
- **Quy tắc:** Tỷ lệ chia sẻ **không** nhân vào phụ phí dầu
- **Hệ quả:** Quy tắc riêng của mô hình Long Minh

- **#:** 5
- **Quy tắc:** **Làm tròn riêng J và H đến từng đồng** rồi mới cộng; đúng nửa đồng làm tròn lên (half-up)
- **Hệ quả:** Không làm tròn gộp K trước

- **#:** 6
- **Quy tắc:** Lít định mức khứ hồi = quãng đường 1 chiều × 2 × định mức phù hợp đơn vị
- **Hệ quả:** Giữ chính xác tham số đến bước tính tiền

- **#:** 7
- **Quy tắc:** Chọn kỳ giá theo **Ngày vận chuyển** trừ độ trễ (lag) hợp đồng; kỳ tương lai chưa hiệu lực không áp sớm
- **Hệ quả:** Kết quả của cùng ngày + khách + tuyến + loại xe phải **duy nhất**

- **#:** 8
- **Quy tắc:** Kỳ giá mới **không đổi** cước đã phát hành
- **Hệ quả:** Không hồi tố

- **#:** 9
- **Quy tắc:** Thiếu tham số → nêu rõ; **không tự dùng 0**
- **Hệ quả:** 0 chỉ hợp lệ khi đủ đầu vào và kết quả đúng 0

- **#:** 10
- **Quy tắc:** Không áp mô hình Long Minh cho hợp đồng khác khi chưa có căn cứ""",
"""1. **KM luôn × 2 (khứ hồi)**, kể cả chuyến 1 chiều hoặc chiều về rỗng. Hệ quả: cước không phụ thuộc việc tận dụng xe/ghép chuyến; ghép/kết hợp **không** thay đổi cước hợp đồng của từng lệnh.
2. **H không âm** — kẹp về 0 khi G < F. Hệ quả: dầu rẻ thì cước = J và công ty không giảm cước; đây là **0 thật**, khác với thiếu tham số.
3. **% chia sẻ cộng vào giá gốc J**, không chỉ thu % của phụ phí dầu; % không phụ thuộc loại xe (thuộc tuyến). Hệ quả: tỷ lệ chia sẻ thuộc **cặp khách hàng–tuyến**.
4. Tỷ lệ chia sẻ **không** nhân vào phụ phí dầu. Hệ quả: đây là quy tắc riêng của mô hình Long Minh.
5. **Làm tròn riêng J và H đến từng đồng** rồi mới cộng; đúng nửa đồng làm tròn lên (half-up). Hệ quả: không làm tròn gộp K trước.
6. Lít định mức khứ hồi = quãng đường 1 chiều × 2 × định mức phù hợp đơn vị. Hệ quả: giữ chính xác tham số đến bước tính tiền.
7. Chọn kỳ giá theo **Ngày vận chuyển** trừ độ trễ (lag) hợp đồng; kỳ tương lai chưa hiệu lực không áp sớm. Hệ quả: kết quả của cùng ngày + khách + tuyến + loại xe phải **duy nhất**.
8. Kỳ giá mới **không đổi** cước đã phát hành. Hệ quả: không hồi tố.
9. Thiếu tham số thì nêu rõ; **không tự dùng 0**. Hệ quả: 0 chỉ hợp lệ khi đủ đầu vào và kết quả đúng 0.
10. Không áp mô hình Long Minh cho hợp đồng khác khi chưa có căn cứ."""))

ok = True
for i, (old, new) in enumerate(P):
    n = src.count(old)
    if n != 1:
        print(f"BLOCK {i+1}: found {n} times — ABORT")
        ok = False
if not ok:
    sys.exit(1)
for i, (old, new) in enumerate(P):
    src = src.replace(old, new)
    print(f"block {i+1} replaced")

open("after/spec-2.md", "w").write(src)
print("written after/spec-2.md", len(src))
