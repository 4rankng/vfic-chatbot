---
# Ca làm việc và lịch làm việc của dự án.
# Mỗi lịch là một khối "### record: <id>". Giờ viết dạng HH:MM (VD: 07:30).
schema_version: "1.0"
category: work_schedules
---

## work_schedules

<!--
Ví dụ khối một lịch làm việc:

### record: lich-lam-chung
job_ids:
- "[Áp dụng cho việc nào? Điền id việc; bỏ trống nếu áp dụng cho mọi việc.]"
work_days:
- "[Làm ngày nào? Ví dụ: Thứ 2. Mỗi dòng một ngày.]"
shifts:
| name | start_time | end_time | crosses_midnight |
| --- | --- | --- | --- |
| "[Tên ca? Ví dụ: Ca ngày]" | "[Bắt đầu mấy giờ? HH:MM]" | "[Kết thúc mấy giờ? HH:MM]" | [true nếu kết thúc sau nửa đêm, không thì false]
rotation: "[Ca luân phiên thế nào?]"
breaks:
- "[Giờ nghỉ? Ví dụ: Nghỉ trưa 12:00 - 13:00. Mỗi dòng một khung giờ.]"
overtime: "[Quy định tăng ca?]"
notes: "[Ghi chú thêm?]"
-->
