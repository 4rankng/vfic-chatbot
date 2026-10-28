# 5. Cước phí, chứng từ vận đơn và báo giá


![Sơ đồ quy trình tính cước](https://bot.tingting.vip/wiki-assets/tinh-cuoc.svg)


> **Sơ đồ:** [Sơ đồ quy trình tính cước](https://book.tingting.vip/s/silversea/p/artifact-214cc718911bdf1c06ec8ac6)

Chương này nói về phần tiền của luồng vận tải Silversea: danh mục cước và phí, cách tính một cước, tính cước tự động, khai báo chi phí, chứng từ vận đơn (tờ khai, bill/booking, debit note) và Báo giá. Các con số trong chương là mốc đối chiếu để kiểm tra khi triển khai, không phải thông báo giá hiện hành.

Ba nguyên tắc nền: thao tác trực tiếp, không có phê duyệt nội bộ; không thay giá trị chưa biết bằng 0 — thiếu dữ liệu thì ghi `—` hoặc một nhãn nêu đúng phần thiếu; không hồi tố cước đã chốt, mọi mốc áp giá lấy theo Ngày vận chuyển.

Phần mô tả cột, ô nhập, popup của các màn liên quan nằm ở [Chương 10](10-y-u-c-u-giao-di-n-ng-i-d-ng-ui-ux.md); chương này chỉ giữ nghiệp vụ.

---

## 5.1 Danh mục phí / cước

### 5.1.1 Phân tầng cước một chuyến (mô hình Long Minh)

Một chuyến chỉ có một cước cuối, và cước cuối cộng dồn từ hai lớp: một lớp tĩnh là cước đã chia sẻ, một lớp động là phụ phí dầu.

```
CƯỚC GỒM PHỤ PHÍ K  =  GIÁ CƯỚC ĐÃ CHIA SẺ J (TĨNH)  +  PHỤ PHÍ DẦU H (ĐỘNG)
```

Đọc từng ký hiệu theo thứ tự nó thay đổi:

| Ký hiệu | Tên | Bản chất | Đổi khi nào |
|---|---|---|---|
| `I` | Giá gốc | Trước chia sẻ và phụ phí dầu | Chỉ khi đàm phán lại hợp đồng |
| `% chia sẻ` | Tỷ lệ chia sẻ | Thuộc cặp **khách hàng – tuyến** | Theo hợp đồng |
| `J` | Cước chia sẻ = `I × (1 + % chia sẻ)` | TĨNH | Chỉ khi đổi `I` hoặc `% chia sẻ` |
| `H` | Phụ phí dầu | ĐỘNG theo kỳ giá dầu | Mỗi kỳ áp giá |
| `K` | Cước cuối = `J + H` | Kết quả tính | Tự tính |
| `L` | Kiểm tra = `K − J` | Luôn bằng `H` — kiểm tra ngược, không phải phí thứ ba | Tự tính |

Tham số tính cước chia làm ba nhóm. Tĩnh (theo hợp đồng): `I`, `% chia sẻ`, KM, `D` định mức, `F` = 17.842,59 — chỉ đổi khi ký lại hợp đồng. Động: `G` giá dầu kỳ, giữ một giá trị duy nhất cho cả bảng cước. Dẫn xuất: `E`, `H`, `J`, `K`, `L` — không nhập tay. Hệ thống phải giữ được công thức kèm đầu vào có ngày hiệu lực, giữ nguyên bản cước đã khóa, và không dùng tổng cước của kỳ cũ làm giá gốc cho kỳ mới.

### 5.1.2 Cước thu và cước trả

Trên bảng Kế hoạch điều động tổng hợp, tiền của mỗi lô tách hai nhóm. Nhóm PHẢI THU gồm cước thu auto · Lạch Huyện auto · Phụ phí auto · Phát sinh (CUS) · Tổng thu, tính từ bảng giá thu khách cộng phần tự tính. Nhóm PHẢI TRẢ gồm cước trả ĐV · Lạch Huyện (điều vận) · Phát sinh (điều vận) · Tổng 1 · Phí RU, lấy từ bảng giá trả nhà xe cộng phần khai báo. Danh sách cột hiển thị ở file giao diện (Chương 10, §5.1.2).

- Cước thu dự kiến là cước tự tính theo hợp đồng, chỉ đọc. Giá đã phát hành là số trên bảng kê, để tách riêng: sửa lô không tự cho sửa giá đã phát hành.
- Cước chính theo lô chỉ tính các chân vận chuyển còn hiệu lực; chân hủy không tính cước; lớp tổng và lớp chi tiết luôn khớp nhau. Cước đóng băng lúc phát hành lô (khi chưa gắn chân) vẫn vào lớp tổng dù chi tiết chưa hiển thị, và không suy ra 0.
- Phụ phí vùng đọc theo bậc nguồn: điều vận nhập › tổng chi phí lái xe ứng trước › cấu hình phụ thu theo cảng. Hết nguồn thì ghi `—`, không bao giờ tự điền 0.

### 5.1.3 Danh mục “Chi phí khác” của Báo giá

Danh mục đủ các dòng theo yêu cầu của khách hàng: Mở tờ khai (thông thường / hàng đặc thù) · Hải quan giám sát (xanh-vàng / đỏ) · Nâng/Hạ Lạch Huyện · Lưu ca xe · Soi chiếu · Kiểm hóa · Kẹp chì.

- Hải quan giám sát và Nâng/Hạ Lạch Huyện được gán cột riêng; các phí còn lại nằm cột chi phí khác, và tên phí phải xuất hiện trong ghi chú bảng kê.
- Mức tiền là giá trị mặc định sửa được: sửa mức của một khách không ảnh hưởng khách khác, và không cắm cứng số trong cấu hình.
- Kiểm hóa và Mở tờ khai – hàng đặc thù để trống mặc định, nhập tay theo từng lô.

### 5.1.4 Phí Lạch Huyện — 2 cơ sở SITC

Phí tính theo đầu nâng/hạ: một đầu trong vùng = 1×, cả hai đầu = 2× (ví dụ nâng Hateco + hạ SITC Lạch Huyện = 1.000.000đ), cả hai đầu ngoài vùng = 0; mức phí đọc từ cấu hình, không cắm cứng.

Danh mục cảng có hai bản ghi phân biệt: `Bãi SITC - Đình Vũ` (Hải Phòng) và `SITC - Lạch Huyện` (Lạch Huyện); bổ sung cơ sở mới không đổi gì ở bản ghi cũ. Mã tuyến trung tính với cơ sở — Lạch Huyện là dữ liệu depot, không nằm trong mã (áp dụng từ 24/09). Trên ứng dụng lái xe, hệ thống tự cộng Nâng/Hạ Lạch Huyện, lái xe không điền tay.

### 5.1.5 Danh mục phí kế thừa khi nhập file cước

Bản khung mới kế thừa nguyên vẹn danh mục phí của bản trước của cùng khách, gồm tên phí, loại phụ, số tiền mặc định, gán cột riêng, ghi chú và thứ tự. File cước chỉ mang số liệu cước; còn danh mục phí mang theo giữa các hợp đồng, không reset mỗi lần nhập. Nhập lần đầu thì danh mục rỗng, và thiếu cấu hình không tự thay bằng giá minh họa.

### 5.1.6 Nhóm chi phí ở màn khai báo

Kết thúc lô, lái xe xử lý hai bảng chi phí: Chi phí lô hàng và Tiền đường. Tiền đường do hệ thống tự ghi nhận, kế toán điều chỉnh, lái xe chỉ nhìn không điền. Nâng/Hạ Lạch Huyện hệ thống tự cộng, lái xe không điền tay. Ở dòng Loại chi phí…, lái xe chọn loại và điền số tiền; thêm chi phí liên tục được, không lưu từng lần giữa chừng.

Ở Kiểm soát phơi phiếu → Thêm khoản chi, nhóm chi phí chỉ hiện hai nhóm: Tiền đường và Chi phí lô hàng; các chi phí khác do Ops điền, kế toán duyệt.

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

Công thức tổng hợp, gộp mọi bước thành một dòng:

```
Cước 1 chuyến = GiáGốc × (1 + %ChiaSẻ)
              + max(0, (GiáDầuKỳ − 17.842,59) × (KmMộtChiều × 2 × ĐịnhMứcDầu))
```

Tầng dữ liệu: `Cước điều chỉnh = Giá gốc × (1 + Tỷ lệ chia sẻ / 100)`, trong đó tỷ lệ thuộc cặp khách hàng–tuyến; `Phụ phí dầu = (Giá dầu kỳ − Giá dầu mốc) × Lít định mức khứ hồi`, kết quả không âm; tỷ lệ chia sẻ không nhân vào phụ phí dầu.

### 5.2.2 Các quy tắc tính bắt buộc

1. KM luôn nhân 2 (khứ hồi) với mọi chuyến, kể cả chạy 1 chiều hoặc chiều về rỗng. Cước báo theo hợp đồng, không phụ thuộc việc tận dụng xe hay ghép chuyến; ghép hoặc kết hợp chuyến không thay đổi cước hợp đồng của từng lệnh.
2. `H` không âm (áp dụng từ 09/09/2026): dầu xuống dưới mốc thì `H = 0` và cước bằng đúng `J`; phép tính phải kẹp `H` về 0 để `K ≥ J`.
3. `% chia sẻ` cộng vào `J`, không chỉ thu phần trăm trên phụ phí dầu; tỷ lệ không phụ thuộc loại xe, áp chung cả khối, và là thuộc tính của tuyến.
4. Làm tròn riêng `J` và `H` đến từng đồng rồi mới cộng thành `K`; nửa đồng làm tròn lên (half-up); không làm tròn gộp trước.
5. Chỉ bù phần chênh dầu, không tính lại toàn bộ tiền dầu vì tiền dầu đã nằm trong `I`.
6. `F` là hằng số: 19.270 đ/lít là giá niêm yết ngày 26/02/2026 đã gồm VAT 8%, chia cho 1,08 để quy về chưa VAT (vì cước cũng báo chưa VAT); chỉ đổi khi ký lại giá gốc, không tự đổi. Chuẩn `17.842,5926` lưu đầy đủ dạng numeric 12,4; `17.842,59` chỉ là giá trị hiển thị — không bao giờ lưu `F` đã làm tròn.

### 5.2.3 Hệ số ô và làm tròn phụ phí (khung Báo giá)

Mỗi ô lưới giá giữ ba thứ: hệ số, tổng lít/chuyến, và giá cos (giá gốc đã nhân tỉ lệ chia sẻ nhà máy).

```
Phụ phí (ô) = chênh lệch giá dầu × lít/chuyến × hệ số của ô
Giá cos      = Giá gốc × (1 + tỉ lệ chia sẻ)      ← KHÔNG nhân hệ số
```

Hệ số áp ở mức ô: hệ số = 1 thì mọi số giữ nguyên, và đổi một ô không ảnh hưởng ô khác cùng nhà máy. Làm tròn phụ phí dùng hàm ROUND của Excel, tức nửa ra xa số 0 (khác cắt cụt): 823.250 → 820.000, còn mốc giữa 825.000 → 830.000. Chỉ phụ phí làm tròn, giá cos không làm tròn. Khách chưa cấu hình thì hành vi vẫn xác định và có kiểm thử khóa. Tổng lít/chuyến là số dẫn xuất (lít = km khứ hồi × định mức), không nhập tay và không tự chế định mức.

### 5.2.4 Thứ tự xác định khi tính cước

Khi tính một cước, hệ thống đi qua chín bước theo đúng thứ tự này:

1. **Khách hàng** — khách nhập file phân biệt theo tên và mã số thuế.
2. **Tuyến hoặc nhóm tuyến** — không lấy theo nhà máy/bên nhận hàng, không lấy mức của khách hoặc tuyến khác.
3. **Loại xe hoặc hạng**.
4. **Ngày vận chuyển** — không dùng ngày tạo lô, không dùng ngày lập hóa đơn.
5. **Trừ độ trễ**: Ngày vận chuyển − N.
6. **Chọn kỳ giá dầu có hiệu lực**.
7. **Ngưỡng điều chỉnh**.
8. Tính `E, H, J, K`.
9. **Khóa cước**.

Nhà máy hoặc bên nhận hàng không thay thế được tuyến trong hợp đồng. Cùng một ngày + khách + tuyến + loại xe thì kết quả phải rõ ràng và duy nhất. Khi hợp đồng cho phép, thứ tự ưu tiên giá là: (1) giá gốc theo kg → (2) giá theo container/loại xe → (3) nhập hoặc điều chỉnh thủ công bởi người có quyền. Thiếu dữ liệu không phải là giá 0.

### 5.2.5 Bốn nhóm điều khoản áp giá

1. **Độ trễ (lag)**: giá công bố ngày D, hợp đồng có lag N thì áp từ D+N; ngày đối chiếu = Ngày vận chuyển − N. NEWEB có N = 1; ASKEY và SUNRISE+SJ chưa có số → báo thiếu, không tự dùng 0.
2. **Ngưỡng kích hoạt**: chọn một trong hai kiểu — % thay đổi giá dầu hoặc số tiền/lít, tối đa một cách; đúng bằng ngưỡng là ĐẠT (áp dụng từ 20/09/2026). Ví dụ 5% hoặc 1.500đ chưa phải ngưỡng của Long Minh. “Đã thỏa thuận không dùng ngưỡng” khác “chưa điền”: ô trống không có nghĩa là luôn áp giá mới.
3. **Hiệu lực kỳ mới**: nhập giá kèm ngày hiệu lực rồi lưu trực tiếp; kỳ tương lai ghi rõ nhưng không áp trước khi có hiệu lực; không tự thay cước đã khóa hoặc đã phát hành; thiếu kỳ thì chỉ rõ thiếu kỳ.
4. **Khóa cước**: lấy Ngày vận chuyển cộng đủ đầu vào để giữ bản cước. Đổi ngày mà còn quyền sửa thì thấy được ảnh hưởng giá, lưu bản kế, vẫn xem được bản cũ. Chứng từ đã phát hành không tự đổi theo; muốn điều chỉnh thì phải có quyền và có lý do.

### 5.2.6 Trị giá tham chiếu — 3 tuyến Long Minh

Khách `LONG MINH` (mã `LONGMINH`) có ba khối bảng giá, và ba khối này là ba nhóm tuyến/nhà máy đích, không phải ba khách:

| Tuyến (nhà máy đích) | KM 1 chiều | KM 2 chiều | % chia sẻ | Hệ số J |
|---|---:|---:|---:|---:|
| Hải Phòng – NEWEB | 130 | 260 | **2%** | ×1,02 |
| ASKEY | 100 | 200 | **4%** | ×1,04 |
| SUNRISE + SJ | 120 | 240 | **2,5%** | ×1,025 |

Nhà máy và pháp nhân: NEWEB → `NEWEB-KHO 1/2/3`; ASKEY → `ASKEY - XƯỞNG 1/2`; SUNRISE+SJ → `SUNRISE`, `SJ TECH` (2 pháp nhân, cùng KCN Vân Trung, dùng chung 1 khối giá vì cùng cự ly) — quan hệ báo giá không phải 1–1 với nhà máy.

Định mức dầu `D` (lít/km) — giống nhau cho cả 3 tuyến, chỉ theo loại xe:

| Loại xe | 1.25T | 2.5T | 3.5T | 5T | 8T | 10T | 15T | CONT 20 | CONT 40 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `D` | 0,10 | 0,13 | 0,13 | 0,15 | 0,20 | 0,24 | 0,30 | 0,32 | 0,35 |

Giá gốc `I` (đ, chưa chia sẻ):

| Loại xe | NEWEB | ASKEY | SUNRISE+SJ |
|---|---:|---:|---:|
| 1.25T | 1.300.000 | 1.200.000 | 1.300.000 |
| 2.5T | 1.700.000 | 1.600.000 | 1.700.000 |
| 3.5T | 1.800.000 | 1.700.000 | 1.800.000 |
| 5T | 2.400.000 | 2.300.000 | 2.400.000 |
| 8T | 2.900.000 | 2.800.000 | 2.900.000 |
| 10T | 3.100.000 | 3.000.000 | 3.100.000 |
| **15T** | **thiếu** | **thiếu** | **thiếu** |
| CONT 20 | 3.900.000 | 3.800.000 | 3.900.000 |
| CONT 40 | 4.100.000 | 4.000.000 | 4.100.000 |

NEWEB và SUNRISE/SJ dùng chung `I` (khác km và % chia sẻ); `I` của ASKEY thấp hơn NEWEB đúng 100.000đ cho mỗi loại xe; 2.5T và 3.5T dùng chung `D` nên `H` bằng nhau, `K` chỉ khác ở `I`.

Kỳ giá tham chiếu: ngày 11/7/2026 thì `G` = 21.740 (chênh 3.897,41); ngày 18/7/2026 thì `G` = 27.620 (chênh 9.777,41) — đây là giá tham chiếu, không phải thông báo giá hiện hành. Cước thành phẩm kỳ 18/7 theo mẫu `lít | H → K`: CONT 40 NEWEB = 91,0 \| 889.744 → **5.071.744**; 15T thì thiếu giá gốc. Δ giá dầu 5.880 nên ΔH đúng bằng `5.880 × E`. Mốc ngày cước thuộc năm 2026.

### 5.2.7 Hạng container theo trọng tải

Thiếu trọng tải thì chặn ra giá container và báo rõ “thiếu trọng tải”, không mặc định hạng nhẹ; biên là 20 tấn, tải ≥ 20 tấn = nặng. Ô giá cos của hạng nặng để trống thì không chặn: nó kế thừa giá hạng nhẹ và gắn nhãn “kế thừa hạng nhẹ / giá tạm”. Tóm lại, thiếu trọng tải thì chặn, thiếu giá hạng nặng thì kế thừa, hai việc khác nhau và không gộp. Lưới giá có 6 hạng hàng lẻ (1.25T–10T) và 4 hạng container (Cont 20 <20t / >20t, Cont 40 nhẹ/nặng).

### 5.2.8 Giá cuối đàm phán (Bảng kê / Debit Note)

Cước tự tính là giá chuẩn theo hợp đồng, chỉ đọc, dùng để so sánh với giá cuối thực tế đàm phán do Kế toán nhập. Giá cuối khác giá hợp đồng thì phải có lý do có nội dung kèm chênh lệch và tổng tiền, và lưu trực tiếp trong phạm vi quyền. Hệ thống giữ ai sửa, giá cũ, giá mới và lý do; giá cuối không làm mất đầu vào tính cước. Chứng từ hoặc kỳ đã khóa được bảo vệ: điều chỉnh phải để dấu vết và ảnh hưởng tiền đúng một lần. Ngoại lệ giá hoặc công nợ: làm trực tiếp trong phạm vi, hạn mức, thời hạn và lý do hợp lệ.

---

## 5.3 Tính cước tự động

### 5.3.1 Phạm vi & vai trò

Phạm vi hiện nay là Long Minh (NEWEB, ASKEY, SUNRISE+SJ); chưa tự áp biểu cước này cho khách khác khi chưa biết hợp đồng của họ.

- **Điều vận (CUS)**: nhập lô + Ngày vận chuyển, xem giá tự tính hoặc lý do chưa tính được.
- **Kế toán / CUS có quyền**: nhập kỳ giá dầu, ngày hiệu lực, nguồn; xem lịch sử giá.
- **QL biểu cước (có quyền)**: lưu trực tiếp giá gốc, điều khoản tuyến, định mức theo hợp đồng.
- **Kế toán (có quyền)**: đối soát, nhập giá cuối + lý do khi lập Bảng kê / Debit Note.

Vai trò không quyền thì không sửa giá; bỏ bước duyệt không đồng nghĩa với mở quyền tài chính cho mọi người.

### 5.3.2 Luồng chính

- **4.1 Nhập kỳ giá dầu**: giá, ngày hiệu lực, nguồn → kiểm tra (lỗi báo ngay ở trường cần sửa, giữ nguyên nội dung đã gõ) → lưu trực tiếp, và thấy ngay kỳ vừa ghi nhận. Giá phải cùng cơ sở so sánh với mốc hợp đồng (chưa VAT); mốc `19.270/1,08` không tự đổi; kỳ ghi Người nhập.
- **4.2 Tính cước khi lập/bổ sung lô**: khách → tuyến → loại xe → Ngày vận chuyển → điều khoản + kỳ giá → `J/H/K`. Đủ đầu vào thì hiện cước đã khóa kèm cách tính và nguồn. Thiếu thì nêu rõ thiếu ở giá gốc / ngày / lag / ngưỡng / kỳ giá — không báo 0 là cước đúng; lô thiếu giá vẫn lưu được nhưng chưa sẵn sàng phát hành số tiền.
- **4.3 Xem/sửa lịch & giá**: xem cước khóa và từng thành phần ngay trên hồ sơ; còn quyền sửa ngày thì thấy giá cũ/mới và lưu lịch sử; hồ sơ khóa thì hệ thống giải thích kèm cách điều chỉnh hợp lệ, không thêm bước xin duyệt.
- **4.4 Nhập file cước Excel**: tạo bản khung mới hiệu lực từ ngày nhập, không ghi đè bản cũ, và kế thừa danh mục phí.

### 5.3.3 Chốt cước khi phát lệnh (lớp cước AUTO)

- Lớp 1 cước vận tải (AUTO) đọc theo bản chốt mới nhất: cước lưu theo từng bản chốt (đổi Ngày vận chuyển hoặc phát lệnh là chốt một bản mới); bản bị thay không cộng vào tổng nào; lô khóa kỳ thì đọc số đã đóng băng; lớp tổng luôn khớp bảng 2.1 và là giá trị cuối cùng khi lập bảng kê/debit.
- Cước FCL chốt theo container của chuyến khi phát lệnh: lấy loại container và lịch hẹn từ chính lô điều vận, nên lô FCL không còn bị bỏ sót cước khi thiếu tuyến ở cấp lô; trường hợp chạy ngoài quy trình chuẩn vẫn miễn và không tự đặt giá.

### 5.3.4 Vận hành khi giá dầu đổi

1. Người có quyền nhập giá dầu mới, ngày hiệu lực, nguồn; ghi rõ chưa VAT hay đã quy đổi; không tự đổi mốc `19.270/1,08`.
2. Lưu trực tiếp kỳ mới; kỳ tương lai ghi rõ là chưa hiệu lực; không có bước gửi duyệt giá.
3. Nhập Ngày vận chuyển → chọn kỳ theo thứ tự trừ độ trễ của tuyến, áp ngưỡng, tính và khóa cước.
4. Mở kỳ dầu mới không tự thay cước đã khóa hoặc số đã phát hành; đổi Ngày vận chuyển mà còn quyền sửa thì giữ bản cũ kèm lý do, chứng từ phát hành không bị sửa âm thầm.

### 5.3.5 Cập nhật báo giá khi có kỳ giá dầu mới

Kế toán nhập kỳ mới → hiện danh sách khách bị ảnh hưởng. Đồng ý = tính theo giá mới · Không = giữ nguyên · Để sau = giữ giá cũ nhưng còn trạng thái chờ. Lô phát sinh trong lúc chờ thì giữ giá cũ, không hồi tố. Chỉ Kế toán mới tích được Đồng ý.

### 5.3.6 Đối chiếu

Đối chiếu phải khớp bảng tham chiếu đúng kỳ và nêu rõ 15T thiếu · dầu dưới mốc thì `H = 0` · 1 chiều vẫn km×2 · làm tròn `J`/`H` không lệch đồng · Ngày vận chuyển + lag quyết định kỳ · mở kỳ mới không đổi cước khóa · lưu trực tiếp có lý do/lịch sử.

---

## 5.4 Khai báo chi phí

### 5.4.1 Phân tách theo 3 nhóm người chi

- **Lái xe**: khai chi phí trên 2 bảng khi kết thúc lô; chọn loại chi phí và điền số tiền; thêm liên tục mà không lưu từng lần (giao diện chi tiết §5.1.6 Chương 10).
- **Ops**: điền tất cả chi phí lô hàng; khai từ Kế hoạch làm hàng; hệ thống cảnh báo khi lô đã có người nhập trước.
- **Kế toán**: duyệt chi phí Ops/lái xe, thêm khoản chi ở Kiểm soát phơi phiếu, lập phiếu thu/chi, chốt debit.

### 5.4.2 Quyền khai chi phí Ops

- Chỉ điều vận (Ops) được khai chi phí; nút thật có tên “Khai chi phí”. Áp dụng từ 17/10: mọi Ops khai chi phí mọi lô — không còn kiểm tra chủ sở hữu lô khi ghi, người điều vận không bị từ chối khi bấm Lưu, và người không phải Ops ghi sẽ bị từ chối quyền.
- Cảnh báo nhập trùng: hệ thống báo trùng và nêu tên người nhập trước — “ĐÃ ĐƯỢC … NHẬP TRƯỚC ĐÓ, BẠN VẪN TIẾP TỤC NHẬP CHỨ”; dòng đã hủy không cảnh báo.
- Chưa có nút khai chi phí trên trang chi tiết lô, chỉ qua Kiểm soát phơi phiếu.

### 5.4.3 Chứng từ hóa đơn & chụp ảnh

- Ở ô Chụp / Chọn ảnh: Ops có thể chụp hoặc không, và việc không chụp không bị ghi nhận là thiếu chứng từ — Ops in hóa đơn đặt bàn kế toán đối soát.
- Yêu cầu về chụp biên lai còn mâu thuẫn: có nguồn bắt buộc chụp biên lai, có nguồn chỉ yêu cầu tùy chọn (đặc tả ngày 19/10), còn ứng dụng lái xe đặt ở mức tùy chọn — **Chưa chốt: bắt buộc với ai, không tự chọn**.
- Ô đánh dấu là cờ có hóa đơn (bật mới yêu cầu số hóa đơn); “Nhập thu/trả bằng nhau” bật thì 2 giá trị đi cùng nhau, tắt thì sửa độc lập, không áp ngầm. Nhà cung cấp mặc định là tên nhà xe chạy tuyến đó; thêm liên tục nhiều dòng mà không lưu từng lần.

### 5.4.4 Thêm khoản chi của Kế toán (Kiểm soát phơi phiếu)

Phiếu nhập gồm nhóm chi phí · tên khoản chi · bên thực chi · nhà cung cấp · số hóa đơn – ngày hóa đơn (có thể điền hoặc không) · “Nhập thu/trả bằng nhau”. Chọn “Bên thực chi” thì hiện 3 mục chi phí. Ở bảng duyệt tiền đường có cột Tích duyệt/Từ chối, và chỉ dòng ĐÃ DUYỆT mới vào phiếu chi trả lái xe; “Đã duyệt” chính là cột Tiền đường của bảng kiểm soát phơi phiếu.

### 5.4.5 Số liệu, số âm, quỹ, hoàn ứng

- Số tiền mặc định là `1,000,000` cho tất cả trường số tiền, ở tất cả dữ liệu các phân hệ.
- Số âm có kiểm soát: dòng chi phí được mang số âm nhưng mọi tổng xử sự như dòng không tồn tại, dòng vẫn hiện để đối soát; màn nhập vẫn yêu cầu số dương. Khoản chi không thu khách bắt buộc có lý do.
- Nguồn quỹ của phiếu phải khớp dòng chi: chi hộ có hóa đơn → Quỹ tiền mặt; ứng Ops, chi phí lô không hóa đơn, phát sinh Ops, tiền đường, cược container → Quỹ công ty; sai thì phiếu từ chối kèm tên dòng sai quỹ.
- Hoàn ứng: `Còn phải hoàn ứng = Số tiền ĐNTT − Số tiền đã ứng`; kết quả có thể âm → cảnh báo thu lại, không hiện số âm trần. **Chưa chốt: vai trò “phê duyệt Tạm ứng/Hoàn ứng”** — chạm nguyên tắc không phê duyệt nội bộ, cần chủ sản phẩm xác định vai trò.

### 5.4.6 Chưa hoàn thiện

Công nợ vận tải còn mở (khách tự hoãn “tuần sau kiểm tra tiếp”). Với Kế toán chốt Debit: “Xuất debit không được” — đã triển khai theo bảng trạng thái nhưng cần rà kiểm chứng nhận lại.

---

## 5.5 Chứng từ vận đơn & tờ khai liên quan tiền

### 5.5.1 Thứ tự chứng từ

**Chưa chốt: thứ tự chứng từ.** Đặc tả nêu hai thứ tự: ngày 22/10 đặt `BILL/BOOKING → SỐ TỜ KHAI → NHẬP/XUẤT → HÃNG TÀU`; ngày 24/10 (phương án B) đặt XNK trước Số Bill/Booking và Số tờ khai xuống cuối phần Nhận diện lô. Chương này giữ hai thứ tự như hai phương án, không tự chọn. Giữ nguyên hai quy tắc không phụ thuộc thứ tự: phải có Số Bill hoặc Số Booking (chỉ chọn một trong hai), và tờ khai theo từng container (`CUS-05`).

### 5.5.2 Tờ khai hải quan

- Tờ khai gắn theo từng container; lô chỉ gán 1 số thì mặc định copy cho toàn bộ cont, và sửa được từng cont sau khi copy (áp dụng từ 13/10). Việc chuyển đổi và bổ sung dữ liệu cũ cho mô hình theo cont vẫn phải làm.
- Mục Tờ khai hải quan có nút “+ Thêm tờ khai” và xóa dòng; chỉ người có quyền Quản trị / CUS / Quản lý được sửa; lô khóa kế toán thì khóa trường kèm lý do; trùng số thì báo lỗi trùng số.
- Trạng thái “thiếu thông tin”: có tờ khai cấp cont hoặc cấp lô = ĐẦY ĐỦ; không có = VẪN THIẾU.
- Trường “Luồng hải quan” (đỏ/vàng/xanh) không còn dùng trong hệ thống (từ 02/10) — chương này không mô tả lại.

### 5.5.3 Khóa hiển thị nghiệp vụ

Thứ tự khóa hiển thị: Số Bill/Số Booking → số tờ khai → tên khách + ngày chi; vắng hết thì ghi `—`. Mã vận đơn nội bộ (`SHP-*`, `TRP-*`, số #) không bao giờ hiển thị; thiếu khóa nghiệp vụ nghĩa là thiếu thông tin, không tự chế số thay thế.

### 5.5.4 Bảng kê / Debit Note / hóa đơn

- đủ dữ liệu để lập bảng kê gồm 4 điều kiện: hàng hóa, giá, chứng từ, điều kiện kỳ.
- Xuất Debit: một lô chỉ thuộc một đợt, và chọn Debit là chốt công nợ theo đợt. VAT 0/5/8/10% tự nhân, tổng = tiền + VAT.
- Trên Debit/Bảng kê gửi khách: cột BKS bắt buộc lấy từ BKS báo khách, không in BKS thực; Loại xe theo loại xe tính cước thu khách. Chốt PHẢI TRẢ thì dùng BKS thực + loại xe tính cước trả.
- Thiếu dữ liệu thì ghi nhãn “Thiếu cước thu / Thiếu phụ phí…”, không gán 0; còn chờ điều chỉnh cước thì chặn xuất Debit dòng đó (`AC-KT-13`).
- Một lô chỉ thuộc một bảng kê hiệu lực (chọn lại bị chặn + nêu số lô); khoảng ngày lấy theo ngày giao của các lô được chọn. Trường hợp chạy ngoài quy trình chuẩn: chỉ áp cước do khách báo và phí chi hộ, không bỏ qua kiểm tra định mức cước phí.

### 5.5.5 Ghép / tách cước (LCL)

Chiều TRẢ nhà xe (Điều vận) — không đổi: ghép N lô thành một chuyến thì Lô 1 = 100%, Lô 2..N = 0đ, tag `Lẻ · Ghép (k/N)`, lý do 0đ/100% đi theo dòng.

- Tiền đường/lương xe cont nội bộ chỉ tính một lần vào Lô 1: lương lái xe và phụ cấp đường của Lô 2..N được đặt bằng 0 và được ghi nhận là điều chỉnh thủ công.
- Lô 1 tự tra đơn giá Cước trả nhà xe (tra theo bậc: tuyến × loại xe × nhà xe, hiệu lực theo ngày); nhập tay thắng giá tra; không tra thấy thì giữ nguyên giá trị cũ, không bịa 0.
- Hủy ghép hoặc xóa Lô 1 thì Lô 2 lên Lô 1, chuyển 100% tiền, không mất về 0đ; TỔNG CHI HỘ lô phụ không reset. Ghép khác khách thì chặn.

Chiều THU khách (CUS) — áp dụng từ 21/10/2026 (15:22): cước thu theo từng lô độc lập = đơn giá Tuyến × KH × số lượng, không dồn 100%/0₫ ở chiều thu; tách nhóm không làm thay đổi tổng tiền; Lãi chuyến = Σ thu − trả.

**Chưa chốt: luật 100/0 ở chiều thu.** Đặc tả LCL ngày 17–18/10 đặt luật ghép 5 lô → Lô 1 = 100% `CƯỚC VẬN TẢI (AUTO)`, Lô 2..N = 0; đặc tả ngày 23/10 (mới lập tài liệu, chưa triển khai) tách nhóm chi phí (ĐV) và nhóm doanh thu (CUS), nút [📦 Gộp hàng] bật/tắt cột CHỌO (chỉ LCL), 100/0 chỉ trong nhóm gộp CUS. Chương này ghi rõ từng phương án theo ngày, không tự chọn.

- Báo cáo công nợ đọc cùng kênh với màn hình (một đường đọc duy nhất) để số luôn khớp; lô LCL có nhóm doanh thu hoặc đã ghi nhận điều chỉnh thì áp luật điều chỉnh; FCL và lô không thuộc diện điều chỉnh giữ nguyên số đã chốt. Tách nhóm thì mỗi lô trở lại cước độc lập, nhóm còn lại giữ nguyên hạng xe.
- Xe ảo / xe thực: BKS báo khách (in lên Debit) tách khỏi BKS thực (trả nhà xe); CUS để trống thì lấy BKS thực do Điều vận gán.

### 5.5.6 Khóa lô & bảng quyết toán

- Khóa lô là đóng băng tổng phải thu/trả, nhóm chi phí, nhãn cảng nâng/hạ tại thời điểm khóa; sửa chi phí bị chặn; trường theo dõi thực tế vẫn bổ sung được; danh mục đổi sau khóa không viết lại chứng từ đã phát hành.
- Bảng quyết toán 2 lớp: lớp tổng + lớp chi tiết (1 dòng/container, kể cả container chưa có phần việc). Dòng chi hộ có hóa đơn tự tính lại số thu khách theo quy tắc loại chi phí; chỉ Phí khác (không hóa đơn) do CUS gõ tay; dòng đã có số hóa đơn thì khóa, muốn đổi thì sửa tại nguồn.

---

## 5.6 Báo giá

### 5.6.1 Vấn đề & phạm vi

Kế toán dựng và duyệt báo giá từng khách — khung giá có ngày hiệu lực, lưới giá nhà máy × hạng xe, phụ phí theo kỳ dầu — và phải trả lời được “báo giá này thay đổi thì các lô đã chạy tính theo giá nào”. Không thuộc Báo giá: cách tính cước áp cho lô khi phát lệnh (xem phần Quy trình vận tải).

### 5.6.2 Khung báo giá & lưới giá

- Khung theo 1 khách: tên mẫu, giá dầu tham chiếu, lag, quy tắc làm tròn phụ phí, ngày hiệu lực, chế độ làm tròn theo khách; kèm phiên bản, bản cũ đọc được và không bị ghi đè.
- Lưới giá = `Nhà máy × Tuyến đường × Hạng phương tiện`; mỗi ô giữ hệ số, tổng lít/chuyến (dẫn xuất) và giá cos — công thức ô xem §5.2.3.

### 5.6.3 Nhập / xuất Excel

- Nhận diện khách = tên đầy đủ + mã số thuế; khách chưa có thì báo lỗi, không tự tạo khách mới; nhà máy/tuyến lệch thì báo từng dòng lỗi, không ghi nửa vời; nhập lại thì tạo phiên bản mới.
- Xem trước = lần ghi thật (xem trước = ghi), hủy trước khi ghi không để lại vết. Xuất khớp mẫu, cột lít không thập phân, cửa sổ phiên bản gồm cả hôm nay; nhập file cước thì kế thừa danh mục phí (§5.1.5).

### 5.6.4 Cập nhật & lịch sử phiên bản

Đổi giá dầu + đồng ý thì sinh đúng một phiên bản mới, bản cũ đọc lại nguyên vẹn. Chưa lọc thì chỉ hiện bản mới nhất mỗi khách; lọc khách + khoảng ngày thì đủ bản trong khoảng; mở bản cũ thấy đúng số liệu tại thời điểm đó; tải tệp tính giá khớp chính bản đó.

### 5.6.5 Phí Lạch Huyện & Chi phí khác

Xem §5.1.3 (danh mục chi phí khác, quy tắc cột) và §5.1.4 (Lạch Huyện 0×/1×/2× theo đầu nâng-hạ, đọc cấu hình).

### 5.6.6 Ngoài phạm vi (chờ đặc tả)

- (a) Kế toán chốt debit chi tiết (tab Debit, xuất biểu mẫu) — đã triển khai ở dạng hộp thoại Chọn Debit;
- (b) Định mức Lạch Huyện theo dải giá dầu — chờ khách chốt trước khi triển khai.

---

## 5.7 Ràng buộc kiểm tra

### 5.7.1 Không âm

Số lượng, đơn giá, tiền phụ cấp trên biểu mẫu chuyến phải không âm; dòng chi phí âm hiển thị nhưng không cộng tổng. `H = max(0, …)` nên luôn có `K ≥ J`. Màn nhập yêu cầu số dương, dòng âm chỉ nằm ở tầng đối soát (§5.4.5); hoàn ứng có thể âm thì cảnh báo thu lại.

### 5.7.2 Chặn trùng

- Trùng hiệu lực: 2 mức giá cùng hiệu lực thì báo lỗi có thông báo riêng, không để hai mức cạnh tranh.
- Bấm lưu lặp hoặc mất kết nối: không tạo 2 bản giá hay 2 khoản tiền; chưa rõ kết quả thì báo “cần kiểm tra”, không tự gửi lại khi có mạng, không hứa lưu ngoại tuyến.
- 10 lệnh ghi tài chính (3 điều chỉnh cước, 3 hoàn cược, 4 phơi phiếu) bắt buộc có mã chống lặp, không nhân đôi bút toán.
- 2 người sửa đồng thời: giữ nội dung đang nhập, cho đối chiếu trước khi lưu, không ghi đè âm thầm.
- Nhập chi phí trùng: báo trùng + nêu tên người nhập trước. Lô đã thuộc bảng kê khác: chặn + nêu số lô. Nhập Excel lỗi giữa chừng: không ghi nửa vời, xem trước = lần ghi thật.

Mỗi lỗi có một thông báo riêng, nói rõ trường cần sửa (thiếu giá, trùng hiệu lực, giá không hợp lệ, không có quyền, hồ sơ đã khóa).

### 5.7.3 Làm tròn

`J` và `H` làm tròn riêng đến từng đồng theo half-up; `K = round(J) + round(H)`, không làm tròn gộp trước. Phụ phí báo giá làm tròn theo ROUND của Excel, nửa ra xa số 0 (§5.2.3). Làm tròn đầu vào khi hiển thị không được đổi kết quả tiền. Mở lại hoặc xuất bảng kê phải ra cùng một số tiền, không lệch 1 đồng vì hiển thị rút gọn.

### 5.7.4 Thiếu dữ liệu vs giá hợp lệ

| Trường hợp | Hành vi sản phẩm |
|---|---|
| Giá gốc 15T thiếu | Báo thiếu giá gốc; không báo 0, không lấy riêng tiền phụ phí làm tổng cước |
| Chưa biết độ trễ / ngưỡng / kỳ dầu | Nêu đúng phần thiếu; không dùng 0, số minh hoạ hay giá tuyến/loại xe khác |
| Chưa có Ngày vận chuyển | Lưu được thông tin lô; rõ là chưa xác định cước, không đặt ngày giả |
| Tiền = 0 với đầu vào đầy đủ | Hiển thị 0 đúng nghĩa, không nhầm với thiếu dữ liệu |
| Thiếu trọng tải / thiếu giá hạng nặng container | Chặn, không mặc định hạng nhẹ · giá hạng nặng kế thừa + nhãn “kế thừa / giá tạm” |
| Thiếu dòng bảng giá (LCL AUTO) | Vẫn lưu lớp, không ghi tiền (không bịa 0) |
| Nhãn ngày kỳ / ghi chú ngoài bảng cước | Đối chiếu đúng kỳ giá; không tự biến ghi chú thành biểu cước mới |

15T: áp bừa công thức thì `J = 0`, `K = H` — đó là dữ liệu thiếu, không phải chính sách giá. Phân biệt “Chưa xác định” / `—` / `0` trên mọi màn, định dạng số dùng chung; thiếu giá 15T hiện `—` kèm nhãn “Thiếu giá 15T”; số tiền `1,000,000` toàn phân hệ, trọng lượng theo tấn.

### 5.7.5 Quyền

Hệ thống phân quyền là nguồn sự thật; quyền ghi kiểm theo vai trò, không nới lỏng vai trò mà thiếu nhánh kiểm phạm vi. Mọi lệnh ghi tài chính phải qua cơ chế chống lặp. CUS giữ nguyên phạm vi danh mục phí báo giá hiện tại; không mở thêm quyền danh mục, không tự thêm cột giá phí.

---

## 5.8 Điểm còn mở (chờ chốt nghiệp vụ)

Không tự điền từ ví dụ; lựa chọn chưa trả lời không được thay bằng giả định:

1. Ba giá gốc 15T cho NEWEB / ASKEY / SUNRISE+SJ (giá thật, không phải 0 hay ví dụ).
2. Lag của ASKEY và SUNRISE+SJ — NEWEB đã có N = 1; ví dụ N=0/N=2 chỉ là minh họa.
3. Ngưỡng điều chỉnh: % hoặc số tiền/lít + giá trị thực; xử lý kỳ đầu; ô trống ≠ “luôn áp giá mới”; mốc so sánh qua nhiều kỳ.
4. Khách ngoài Long Minh (mô hình tính cước khác hay không) · nguồn giá dầu (chung/riêng, lịch công bố, cách quy đổi VAT).
5. Định mức Lạch Huyện theo dải giá dầu · Kế toán chốt debit chi tiết — chờ chốt trước khi triển khai.
6. Xung đột chụp ảnh/biên lai (§5.4.3) · Luật 100/0 ở chiều thu LCL (§5.5.5) · Thứ tự chứng từ (§5.5.1).
7. Vai trò “phê duyệt” cho điều chỉnh cước/tạm ứng/hoàn ứng — chạm nguyên tắc không phê duyệt nội bộ.
8. Công nợ vận tải còn mở · Tạo khung giá qua giao diện bị lỗi im lặng · Đơn vị tổng chọn lô: “tấn” hay “kg”.

**Tiêu chí chấp nhận rút gọn**: khớp bảng tham chiếu đúng kỳ + rõ 15T thiếu · dầu dưới mốc `H = 0`, 1 chiều vẫn km×2 · Ngày vận chuyển + lag quyết định kỳ, mở kỳ mới không đổi cước khóa · lưu trực tiếp có lý do/lịch sử · cùng số tiền mọi thiết bị, bấm lặp không tạo tiền trùng · mở bản cũ vẫn thấy số cũ · thiếu dữ liệu không tạo giá giả · 2 cửa sổ sửa không ghi đè âm thầm.
