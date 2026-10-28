# 5. Cước phí, chứng từ vận đơn và báo giá

![Sơ đồ quy trình tính cước](https://book.tingting.vip/files/silversea/so-do/tinh-cuoc.svg)

> **Sơ đồ:** [Sơ đồ quy trình tính cước](https://book.tingting.vip/s/silversea/p/artifact-214cc718911bdf1c06ec8ac6)

Chương này mô tả quy tắc về **tiền** trong luồng vận tải Silversea: danh mục cước/phí, công thức tính cước, tính cước tự động, khai báo chi phí, chứng từ vận đơn (tờ khai, bill/booking, debit note) và Báo giá. Số liệu là **mốc đối chiếu**, không phải thông báo giá hiện hành.

Nguyên tắc nền tảng: **thao tác trực tiếp, không phê duyệt nội bộ**; **không thay giá trị chưa biết bằng 0** — thiếu dữ liệu → `\"—\"` hoặc nhãn nêu đúng phần thiếu; **không hồi tố cước đã chốt** — mốc áp giá = **Ngày vận chuyển**.

---

## 5.1 Danh mục phí / cước

### 5.1.1 Phân tầng cước một chuyến (mô hình Long Minh)

```
CƯỚC GỒM PHỤ PHÍ K  =  GIÁ CƯỚC ĐÃ CHIA SẺ J (TĨNH)  +  PHỤ PHÍ DẦU H (ĐỘNG)
```

- **Ký hiệu:** `I`
- **Tên:** Giá gốc
- **Bản chất:** Trước chia sẻ và phụ phí dầu
- **Đổi khi nào:** Chỉ khi đàm phán lại hợp đồng

- **Ký hiệu:** `% chia sẻ`
- **Tên:** Tỷ lệ chia sẻ
- **Bản chất:** Thuộc cặp **khách hàng – tuyến**
- **Đổi khi nào:** Theo hợp đồng

- **Ký hiệu:** `J`
- **Tên:** Cước chia sẻ = `I × (1 + % chia sẻ)`
- **Bản chất:** **TĨNH**
- **Đổi khi nào:** Chỉ khi đổi `I` hoặc `% chia sẻ`

- **Ký hiệu:** `H`
- **Tên:** Phụ phí dầu
- **Bản chất:** **ĐỘNG** theo kỳ giá dầu
- **Đổi khi nào:** Mỗi kỳ áp giá

- **Ký hiệu:** `K`
- **Tên:** Cước cuối = `J + H`
- **Bản chất:** Kết quả tính
- **Đổi khi nào:** Tự tính

- **Ký hiệu:** `L`
- **Tên:** Kiểm tra = `K − J`
- **Bản chất:** **Luôn bằng `H`** — kiểm tra ngược, không phải phí thứ ba
- **Đổi khi nào:** Tự tính

Tham số: **tĩnh** (hợp đồng) = `I`, `% chia sẻ`, KM, `D` định mức, `F` = 17.842,59, chỉ đổi khi ký lại hợp đồng; **động** = `G` giá dầu kỳ (**1 giá trị duy nhất cho cả bảng cước**); **dẫn xuất** = `E`, `H`, `J`, `K`, `L`, **không nhập tay**. Phải **giữ công thức + đầu vào có ngày hiệu lực** và **giữ bản cước đã khóa**; **không dùng tổng cước kỳ cũ làm giá gốc kỳ mới**.

### 5.1.2 Cước thu và cước trả

Trên bảng Kế hoạch điều động tổng hợp, mỗi lô tách 2 nhóm cột:

- **Nhóm:** **PHẢI THU**
- **Cột:** Cước thu auto · Lạch Huyện auto · Phụ phí auto · Phát sinh (CUS) · Tổng thu
- **Nguồn:** Bảng giá thu khách + tự tính

- **Nhóm:** **PHẢI TRẢ**
- **Cột:** Cước trả ĐV · Lạch Huyện (điều vận) · Phát sinh (điều vận) · Tổng 1 · Phí RU
- **Nguồn:** Bảng giá trả nhà xe + khai báo

- **Cước thu dự kiến** = cước tự tính theo hợp đồng (chỉ đọc); **giá đã phát hành** = số trên bảng kê — tách riêng, sửa lô không tự cho sửa giá.
- **Cước chính theo lô** chỉ tính **chân vận chuyển còn hiệu lực**; chân hủy không tính cước; lớp tổng ↔ lớp chi tiết luôn khớp. Cước đóng băng lúc phát hành lô (chưa gắn chân) vẫn vào lớp tổng dù chi tiết chưa hiển thị — không suy thành 0.
- **Cột phụ phí vùng**: bậc nguồn = điều vận nhập › tổng chi phí lái xe ứng trước › cấu hình phụ thu theo cảng; vắng nguồn → `\"—\"`, không bao giờ tự điền 0.

### 5.1.3 Danh mục “Chi phí khác” của Báo giá

Đủ dòng theo yêu cầu của khách hàng: Mở tờ khai (thông thường / hàng đặc thù) · Hải quan giám sát (xanh-vàng / đỏ) · Nâng/Hạ Lạch Huyện · Lưu ca xe · Soi chiếu · Kiểm hóa · Kẹp chì.

- **Hải quan giám sát** và **Nâng/Hạ Lạch Huyện** → **cột riêng**; các phí còn lại → **cột chi phí khác** VÀ **tên phí phải xuất hiện trong ghi chú bảng kê**.
- Mức tiền = **mặc định sửa được**, sửa mức 1 khách không ảnh hưởng khách khác, **không cắm cứng số trong cấu hình**.
- **“Kiểm hóa”** và **“Mở tờ khai – hàng đặc thù”** để trống mặc định → nhập tay theo từng lô.

### 5.1.4 Phí Lạch Huyện — 2 cơ sở SITC

- Tính theo **đầu nâng/hạ**: 1 đầu trong vùng = **1×**; cả 2 đầu = **2×** (nâng Hateco + hạ SITC Lạch Huyện = 1.000.000đ); cả 2 đầu ngoài vùng = **0**; mức phí đọc từ **cấu hình**, không cắm cứng.
- Danh mục cảng có **hai bản ghi phân biệt**: `Bãi SITC - Đình Vũ` (Hải Phòng) và `SITC - Lạch Huyện` (Lạch Huyện); bổ sung cơ sở mới không đổi bản ghi cũ. **Mã tuyến trung tính với cơ sở** — Lạch Huyện là dữ liệu depot, không nằm trong mã (quyết định ngày 24/09).
- Trên ứng dụng lái xe, **Nâng/Hạ Lạch Huyện hệ thống tự cộng**, lái xe không điền tay.

### 5.1.5 Danh mục phí kế thừa khi nhập file cước

Bản khung mới kế thừa **nguyên vẹn** danh mục phí bản trước của **cùng khách** (tên phí, loại phụ, số tiền mặc định, gán cột riêng, ghi chú, thứ tự). File cước chỉ mang **số liệu cước**, danh mục phí mang theo giữa các hợp đồng, không reset mỗi lần nhập; nhập đầu tiên → danh mục rỗng, **thiếu cấu hình không tự thay giá minh họa**.

### 5.1.6 Nhóm chi phí ở màn khai báo
Kết thúc lô, lái xe thấy **2 bảng chi phí**: *Chi phí lô hàng* + *Tiền đường*; bỏ cột Người chi, bỏ Số hóa đơn & Ngày hóa đơn, thêm 2 ô **Hóa đơn / Phiếu thu**:

- **Tiền đường**: hệ thống tự động ghi nhận, kế toán điều chỉnh; **lái xe chỉ nhìn, không điền**.
- **Nâng/Hạ Lạch Huyện**: hệ thống tự động cộng, lái xe không điền tay.
- **Loại chi phí…**: lái xe chọn + điền số tiền; **thêm chi phí liên tục, không lưu giữa chừng**.

Ở **Kiểm soát phơi phiếu → Thêm khoản chi**, nhóm chi phí **chỉ hiện 2 nhóm: Tiền đường / Chi phí lô hàng** (chi phí khác do Ops điền, kế toán duyệt).

## 5.2 Quy tắc & công thức tính cước

### 5.2.1 Bộ công thức gốc

```
C  (2 CHIỀU)   = B (km 1 chiều) × 2
E  (LÍT/CHUYẾN)= C × D (định mức lít/km theo loại xe)
F  (GIÁ DẦU MỐC)= 19.270 / 1,08 = 17.842,59 đ/lít
G  (GIÁ DẦU KỲ) = giá dầu chưa VAT của kỳ đang tính
H  (PHỤ PHÍ DẦU)= max(0, (G − F) × E)
J  (CƯỚC CHIA SẺ)= I (GIÁ GỐC) × (1 + % chia sẻ)
K  (CƯỚC CUỐI)  = J + H ;   L = K − J ≡ H
```

Công thức tổng hợp:

```
Cước 1 chuyến = GiáGốc × (1 + %ChiaSẻ)
              + max(0, (GiáDầuKỳ − 17.842,59) × (KmMộtChiều × 2 × ĐịnhMứcDầu))
```

Tầng dữ liệu: `Cước điều chỉnh = Giá gốc × (1 + Tỷ lệ chia sẻ / 100)` (tỷ lệ thuộc cặp khách hàng–tuyến); `Phụ phí dầu = (Giá dầu kỳ − Giá dầu mốc) × Lít định mức khứ hồi`, không âm; **tỷ lệ chia sẻ không nhân vào phụ phí dầu**.

### 5.2.2 Các quy tắc tính bắt buộc

1. **KM luôn × 2 (khứ hồi)** mọi chuyến — kể cả 1 chiều hoặc chiều về rỗng; cước báo theo hợp đồng, **không phụ thuộc tận dụng xe/ghép chuyến**, ghép/kết hợp **không thay đổi cước hợp đồng của từng lệnh**.
2. **`H` không âm**: dầu dưới mốc → `H = 0`, cước = đúng `J`; phép tính phải kẹp `H` về 0 để `K ≥ J` (khách xác nhận ngày 09/09/2026: chọn phương án H không âm).
3. **`% chia sẻ` cộng vào `J`**, không chỉ thu % phụ phí dầu; **không phụ thuộc loại xe** — áp chung cả khối, thuộc tính của **tuyến**.
4. **Làm tròn riêng `J`, `H` đến từng đồng** rồi mới cộng `K`; **nửa đồng làm tròn lên (half-up)**; không làm tròn gộp trước.
5. **Chỉ bù phần chênh dầu**, không tính lại toàn bộ tiền dầu (đã nằm trong `I`).
6. **`F` là hằng số**: `19.270 đ/lít` = giá niêm yết 26/02/2026 **đã gồm VAT 8%**, chia `1,08` để quy về chưa VAT (cước cũng báo chưa VAT); chỉ đổi khi ký lại giá gốc, **không tự đổi**. Chuẩn `17.842,5926` lưu đầy đủ (numeric 12,4), `17.842,59` chỉ là hiển thị — **không bao giờ lưu `F` đã làm tròn**.

### 5.2.3 Hệ số ô và làm tròn phụ phí (khung Báo giá)

Mỗi ô lưới giá giữ **hệ số**, **tổng lít/chuyến**, **giá cos** = giá gốc × (1 + tỉ lệ chia sẻ nhà máy):

```
Phụ phí (ô) = chênh lệch giá dầu × lít/chuyến × hệ số của ô
Giá cos      = Giá gốc × (1 + tỉ lệ chia sẻ)      ← KHÔNG nhân hệ số
```

- Hệ số áp **ở mức ô**; = 1 → mọi số giữ nguyên; đổi 1 ô không ảnh hưởng ô khác cùng nhà máy.
- **Làm tròn phụ phí = hàm ROUND của Excel — nửa RA XA số 0** (khác cắt cụt): 823.250 → 820.000; mốc giữa 825.000 → 830.000. **Chỉ phụ phí làm tròn; giá cos KHÔNG làm tròn.** Khách chưa cấu hình → hành vi xác định, có kiểm thử khoá.
- **Tổng lít/chuyến là số dẫn xuất** (lít = km khứ hồi × định mức) — **không nhập tay, không tự chế định mức**.

### 5.2.4 Thứ tự xác định khi tính cước

1. **Khách hàng** (nhập file phân biệt tên + mã số thuế) → 2. **Tuyến/nhóm tuyến** (không lấy theo nhà máy/bên nhận hàng, không lấy mức khách/tuyến khác) → 3. **Loại xe/hạng** → 4. **Ngày vận chuyển** (không dùng ngày tạo lô, không dùng ngày lập hóa đơn) → 5. **Trừ độ trễ** (`Ngày vận chuyển − N`) → 6. **Chọn kỳ giá dầu có hiệu lực** → 7. **Ngưỡng điều chỉnh** → 8. Tính `E, H, J, K` → 9. **Khóa cước**.

Nhà máy/bên nhận hàng **không thay thế tuyến** trong hợp đồng; cùng 1 ngày + khách + tuyến + loại xe → kết quả **phải rõ ràng duy nhất**. Thứ tự ưu tiên giá khi hợp đồng cho phép: **(1) giá gốc theo kg → (2) giá theo container/loại xe → (3) nhập/điều chỉnh thủ công bởi người có quyền**; thiếu dữ liệu ≠ giá 0.

### 5.2.5 Bốn nhóm điều khoản áp giá
1. **Độ trễ (lag)**: giá công bố ngày D, lag N → áp từ D+N; ngày đối chiếu = **Ngày vận chuyển − N**. NEWEB **N = 1**; ASKEY/SUNRISE+SJ **chưa có số** → báo thiếu, **không tự dùng 0**.
2. **Ngưỡng kích hoạt**: **% thay đổi giá dầu** hoặc **số tiền/lít**, **tối đa 1 cách**; **đúng bằng ngưỡng = ĐẠT** (quyết định ngày 20/09/2026); VD 5% / 1.500đ chưa thành ngưỡng Long Minh. **“Đã thỏa thuận không dùng ngưỡng” ≠ “chưa điền”** — ô trống không phải “luôn áp giá mới”.
3. **Hiệu lực kỳ mới**: nhập giá + ngày hiệu lực, **lưu trực tiếp**; kỳ tương lai rõ, không áp trước hiệu lực; **không tự thay cước đã khóa/đã phát hành**; thiếu kỳ → chỉ rõ thiếu kỳ.
4. **Khóa cước**: **Ngày vận chuyển** + đủ đầu vào → giữ bản cước. Đổi ngày (còn quyền sửa): thấy ảnh hưởng giá, lưu bản kế, vẫn xem bản cũ. **Chứng từ phát hành không tự đổi theo** — điều chỉnh có quyền + lý do.

### 5.2.6 Trị giá tham chiếu — 3 tuyến Long Minh

1 khách `LONG MINH` (mã `LONGMINH`); **3 khối bảng giá = 3 nhóm tuyến/nhà máy đích, không phải 3 khách**:

- **Tuyến (nhà máy đích):** Hải Phòng – NEWEB
- **KM 1 chiều:** 130
- **KM 2 chiều:** 260
- **% chia sẻ:** **2%**
- **Hệ số J:** ×1,02

- **Tuyến (nhà máy đích):** ASKEY
- **KM 1 chiều:** 100
- **KM 2 chiều:** 200
- **% chia sẻ:** **4%**
- **Hệ số J:** ×1,04

- **Tuyến (nhà máy đích):** SUNRISE + SJ
- **KM 1 chiều:** 120
- **KM 2 chiều:** 240
- **% chia sẻ:** **2,5%**
- **Hệ số J:** ×1,025

Nhà máy & pháp nhân: NEWEB → `NEWEB-KHO 1/2/3`; ASKEY → `ASKEY - XƯỞNG 1/2`; SUNRISE+SJ → `SUNRISE`, `SJ TECH` (**2 pháp nhân**, cùng KCN Vân Trung, dùng chung 1 khối giá vì cùng cự ly) — **quan hệ báo giá ≠ 1–1 với nhà máy**.

**Định mức dầu `D` (lít/km) — giống nhau cho cả 3 tuyến, chỉ theo loại xe**:

- **Loại xe:** `D`
- **1.25T:** 0,10
- **2.5T:** 0,13
- **3.5T:** 0,13
- **5T:** 0,15
- **8T:** 0,20
- **10T:** 0,24
- **15T:** 0,30
- **CONT 20:** 0,32
- **CONT 40:** 0,35

**Giá gốc `I` (đ, chưa chia sẻ)**:

- **Loại xe:** 1.25T
- **NEWEB:** 1.300.000
- **ASKEY:** 1.200.000
- **SUNRISE+SJ:** 1.300.000

- **Loại xe:** 2.5T
- **NEWEB:** 1.700.000
- **ASKEY:** 1.600.000
- **SUNRISE+SJ:** 1.700.000

- **Loại xe:** 3.5T
- **NEWEB:** 1.800.000
- **ASKEY:** 1.700.000
- **SUNRISE+SJ:** 1.800.000

- **Loại xe:** 5T
- **NEWEB:** 2.400.000
- **ASKEY:** 2.300.000
- **SUNRISE+SJ:** 2.400.000

- **Loại xe:** 8T
- **NEWEB:** 2.900.000
- **ASKEY:** 2.800.000
- **SUNRISE+SJ:** 2.900.000

- **Loại xe:** 10T
- **NEWEB:** 3.100.000
- **ASKEY:** 3.000.000
- **SUNRISE+SJ:** 3.100.000

- **Loại xe:** **15T**
- **NEWEB:** **thiếu**
- **ASKEY:** **thiếu**
- **SUNRISE+SJ:** **thiếu**

- **Loại xe:** CONT 20
- **NEWEB:** 3.900.000
- **ASKEY:** 3.800.000
- **SUNRISE+SJ:** 3.900.000

- **Loại xe:** CONT 40
- **NEWEB:** 4.100.000
- **ASKEY:** 4.000.000
- **SUNRISE+SJ:** 4.100.000

NEWEB & SUNRISE/SJ **dùng chung `I`** (khác km và % chia sẻ); ASKEY `I` thấp hơn NEWEB đúng **100.000đ/loại xe**; **2.5T và 3.5T dùng chung `D`** → `H` bằng nhau, `K` chỉ khác `I`.

**Kỳ giá tham chiếu**: 11/7/2026 → `G` = 21.740 (chênh **3.897,41**); 18/7/2026 → `G` = 27.620 (chênh **9.777,41**) — giá tham chiếu, **không phải thông báo giá hiện hành**. **Cước thành phẩm kỳ 18/7** (`lít | H → K`): CONT 40 NEWEB = 91,0 \| 889.744 → **5.071.744**; 15T = *(thiếu giá gốc)*. Δ giá dầu 5.880 → ΔH đúng `5.880 × E`. Mốc ngày cước thuộc **năm 2026**.

### 5.2.7 Hạng container theo trọng tải

- Thiếu trọng tải → **CHẶN** ra giá container, báo rõ “thiếu trọng tải”, **không mặc định hạng nhẹ**; biên **≥ 20 tấn = nặng**.
- Ô giá cos hạng nặng **để trống → KHÔNG chặn**: kế thừa giá hạng nhẹ + nhãn “kế thừa hạng nhẹ / giá tạm”. **Thiếu trọng tải thì chặn, thiếu giá hạng nặng thì kế thừa — không gộp.**
- Lưới giá cột: 6 hạng hàng lẻ (1.25T–10T) + 4 hạng container (Cont 20 <20t / >20t, Cont 40 nhẹ/nặng).

### 5.2.8 Giá cuối đàm phán (Bảng kê / Debit Note)

Cước tự tính = **giá chuẩn theo hợp đồng** (chỉ đọc) để so sánh với **giá cuối thực tế đàm phán** do Kế toán nhập. Giá cuối ≠ giá hợp đồng → **yêu cầu lý do có nội dung** + chênh lệch + tổng tiền, **lưu trực tiếp trong phạm vi quyền**. Giữ ai sửa, giá cũ/mới, lý do; **giá cuối không thay mất đầu vào tính cước**; chứng từ/kỳ đã khóa được bảo vệ, điều chỉnh có dấu vết và ảnh hưởng tiền **đúng một lần**. Ngoại lệ giá/công nợ: làm trực tiếp trong **phạm vi, hạn mức, thời hạn, lý do hợp lệ**.

---

## 5.3 Tính cước tự động

### 5.3.1 Phạm vi & vai trò
Phạm vi hiện nay: **Long Minh** (NEWEB, ASKEY, SUNRISE+SJ); **không tự áp biểu cước này cho khách khác** khi chưa biết hợp đồng họ.

- **Điều vận (CUS)**: nhập lô + Ngày vận chuyển, xem giá tự tính hoặc lý do chưa tính được.
- **Kế toán / CUS có quyền**: nhập kỳ giá dầu, ngày hiệu lực, nguồn; xem lịch sử giá.
- **QL biểu cước (có quyền)**: lưu trực tiếp giá gốc, điều khoản tuyến, định mức theo hợp đồng.
- **Kế toán (có quyền)**: đối soát, nhập giá cuối + lý do khi lập Bảng kê / Debit Note.

Vai trò không quyền **không sửa giá**; **bỏ bước duyệt ≠ mở quyền tài chính cho mọi người**.

### 5.3.2 Luồng chính

- **4.1 Nhập kỳ giá dầu**: giá, ngày hiệu lực, nguồn → kiểm tra (lỗi ở trường cần sửa, giữ nội dung) → **lưu trực tiếp**, thấy kỳ vừa ghi nhận. Giá phải **cùng cơ sở so sánh** với mốc hợp đồng (chưa VAT); mốc `19.270/1,08` không tự đổi; kỳ ghi **Người nhập**.
- **4.2 Tính cước khi lập/bổ sung lô**: khách → tuyến → loại xe → Ngày vận chuyển → điều khoản + kỳ giá → `J/H/K`. Đủ: hiện cước đã khóa kèm **cách tính và nguồn**. Thiếu: nêu rõ **giá gốc / ngày / lag / ngưỡng / kỳ giá** — **không báo 0 là cước đúng**; lô thiếu giá vẫn lưu được nhưng **chưa sẵn sàng phát hành số tiền**.
- **4.3 Xem/sửa lịch & giá**: xem cước khóa + từng thành phần ngay trên hồ sơ; còn quyền sửa ngày → thấy giá cũ/mới + lưu lịch sử; hồ sơ khóa → giải thích + cách điều chỉnh hợp lệ, **không thêm bước xin duyệt**.
- **4.4 Nhập file cước Excel**: tạo **bản khung mới hiệu lực từ ngày nhập**, không ghi đè, kế thừa danh mục phí.

### 5.3.3 Chốt cước khi phát lệnh (lớp cước AUTO)

- Lớp 1 **cước vận tải (AUTO)** đọc theo **bản chốt mới nhất**: cước lưu theo từng bản chốt (đổi Ngày vận chuyển hoặc phát lệnh = chốt một bản mới); bản bị thay **không** cộng vào tổng nào; lô khóa kỳ đọc số đã đóng băng; lớp tổng luôn khớp bảng 2.1 và là **giá trị cuối cùng** khi lập bảng kê/debit.
- **Cước FCL chốt theo container của chuyến khi phát lệnh**: lấy loại container và lịch hẹn từ chính lô điều vận; lô FCL không còn bị bỏ sót cước khi thiếu tuyến ở cấp lô; trường hợp chạy ngoài quy trình chuẩn vẫn miễn và **không tự đặt giá**.

### 5.3.4 Vận hành khi giá dầu đổi

1. Người có quyền nhập giá dầu mới, ngày hiệu lực, nguồn; rõ chưa VAT hay đã quy đổi; **không tự đổi mốc `19.270/1,08`**.
2. **Lưu trực tiếp kỳ mới**; kỳ tương lai ghi rõ chưa hiệu lực; **không có bước gửi duyệt giá**.
3. Nhập **Ngày vận chuyển** → chọn kỳ **trừ độ trễ tuyến**, áp ngưỡng, tính và **khóa cước**.
4. Mở kỳ dầu mới **không tự thay cước đã khóa/số đã phát hành**; đổi Ngày vận chuyển (còn quyền sửa): giữ bản cũ + lý do, chứng từ phát hành không bị sửa âm thầm.

### 5.3.5 Cập nhật báo giá khi có kỳ giá dầu mới

Kế toán nhập kỳ mới → hiện **danh sách** khách bị ảnh hưởng. **Đồng ý** = tính theo giá mới · **Không** = giữ nguyên · **Để sau** = giữ giá cũ nhưng còn **trạng thái chờ**. Lô phát sinh trong lúc chờ: **giữ giá cũ, không hồi tố**. Chỉ **Kế toán** tích được Đồng ý.

### 5.3.6 Đối chiếu

Khớp bảng tham chiếu đúng kỳ + rõ 15T thiếu · dầu dưới mốc `H = 0` · 1 chiều vẫn km×2 · làm tròn `J`/`H` không lệch đồng · Ngày vận chuyển + lag quyết định kỳ · mở kỳ mới không đổi cước khóa · lưu trực tiếp có lý do/lịch sử.

---

## 5.4 Khai báo chi phí

### 5.4.1 Phân tách theo 3 nhóm người chi
- **Lái xe**: 2 bảng khi kết thúc lô; bỏ cột Người chi; ô Hóa đơn/Phiếu thu; chọn loại chi phí + số tiền; thêm liên tục không lưu từng lần.
- **Ops**: điền **tất cả** chi phí lô hàng; khai từ Kế hoạch làm hàng; cảnh báo lô đã có người nhập trước.
- **Kế toán**: duyệt chi phí Ops/lái xe, thêm khoản chi ở Kiểm soát phơi phiếu, lập phiếu thu/chi, chốt debit.

### 5.4.2 Quyền khai chi phí Ops

- Chỉ **điều vận (Ops)** được khai chi phí; nút thật tên **“Khai chi phí”**. Quyết định ngày 17/10 (Thứ Ba): **“mọi Ops khai chi phí mọi lô”** — không còn kiểm tra chủ sở hữu lô khi ghi; người điều vận không bị từ chối khi bấm Lưu; người không phải Ops ghi sẽ bị từ chối quyền.
- **Cảnh báo nhập trùng**: hệ thống báo trùng và nêu tên người nhập trước — “ĐÃ ĐƯỢC … NHẬP TRƯỚC ĐÓ, BẠN VẪN TIẾP TỤC NHẬP CHỨ”; dòng đã hủy không cảnh báo.
- Chưa có nút khai chi phí trên trang chi tiết lô (chỉ qua Kiểm soát phơi phiếu).

### 5.4.3 Chứng từ hóa đơn & chụp ảnh

- Ô **Chụp / Chọn ảnh**: Ops **có thể chụp hoặc KHÔNG, không ghi nhận thiếu chứng từ** — Ops in hóa đơn đặt bàn kế toán đối soát.
- **Yêu cầu về chụp biên lai còn mâu thuẫn**: có nguồn bắt buộc chụp biên lai, có nguồn chỉ yêu cầu tùy chọn (đặc tả ngày 19/10), ứng dụng lái xe đặt ở mức tùy chọn — **Chưa chốt: bắt buộc với ai, không tự chọn**.
- **Checkbox = cờ có hóa đơn** (bật mới yêu cầu số hóa đơn); “Nhập thu/trả bằng nhau” bật = 2 giá trị đi cùng nhau, tắt = sửa độc lập, không áp ngầm. **Nhà cung cấp** mặc định tên nhà xe chạy tuyến đó; thêm liên tục nhiều dòng không lưu từng lần.

### 5.4.4 Thêm khoản chi của Kế toán (Kiểm soát phơi phiếu)

```
Nhóm chi phí · Tên khoản chi · Bên thực chi · Nhà cung cấp
· Số hóa đơn – ngày hóa đơn (có thể điền hoặc không) · Nhập thu/trả bằng nhau
```
