---
# Tuyến xe đưa đón và lịch xe của dự án.
# Mỗi tuyến là một khối "### record: <id>". Giờ đón viết dạng HH:MM.
schema_version: "1.0"
category: transportation
---

## transportation

<!--
Ví dụ khối một tuyến xe:

### record: tuyen-xe-1
job_ids:
- "[Áp dụng cho việc nào? Điền id việc; bỏ trống nếu áp dụng cho mọi việc.]"
name: "[Tên tuyến? Ví dụ: Tuyến số 1]"
direction: "[Chiều chạy? to_factory | from_factory | round_trip]"
service_days:
- "[Ngày nào có xe? Ví dụ: Thứ 2. Mỗi dòng một ngày.]"
shift: "[Đón cho ca nào? Ví dụ: Ca ngày]"
fee_vnd: [Giá vé bao nhiêu VNĐ? Điền 0 nếu miễn phí.]
stops:
| order | name | time | address |
| --- | --- | --- | --- |
| [Thứ tự điểm đón, bắt đầu từ 1] | "[Tên điểm đón?]" | "[Giờ đón? HH:MM]" | "[Địa chỉ điểm đón?]"
notes: "[Ghi chú thêm?]"
-->
