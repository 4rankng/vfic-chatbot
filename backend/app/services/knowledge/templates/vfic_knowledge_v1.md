---
schema_version: vfic-knowledge-v1
doc_id: lg_display_worker_guide_2026_06
doc_version: 1
title: "LG Display Worker Guide"
company_name: "LG Display"
project_slug: "lg-display"
locale: "vi"
audience:
  - worker
  - customer
content_type: "company_knowledge"
effective_from: "2026-06-01"
effective_to: null
source_owner: "operations"
tags:
  - recruitment
  - salary
  - bus
---

# LG Display Worker Guide

## Company Overview

LG Display Hai Phong is a manufacturing partner recruiting temporary workers for
screen production and inspection at KCN Trang Due, An Duong, Hai Phong.

## Worker Features

Fill every `### Feature: <feature_key>` block. Keep the feature keys unchanged; the app
rejects missing, duplicate, unknown, or inactive keys so the chatbot can retrieve each
worker concern directly.

### Feature: take_home_income

Question: Thu nhập thực nhận khoảng bao nhiêu?

Answer: Thu nhập thực tế ước tính khoảng 10-13 triệu VND/tháng, bao gồm lương,
phụ cấp và tăng ca.

Source: Tin tuyển dụng LG Display, mục Lương và phụ cấp.

### Feature: pay_frequency

Question: VFIC trả lương khi nào?

Answer: VFIC có chương trình trả lương theo tuần cho ứng viên LG Display.

Source: Tin tuyển dụng LG Display, mục Lương tuần.

### Feature: salary_transparency

Question: Lương gồm những khoản nào?

Answer: Lương gồm lương cơ bản, phụ cấp chuyên cần, phụ cấp ca và tiền tăng ca;
ứng viên được tư vấn rõ trước khi đăng ký.

Source: Tin tuyển dụng LG Display, mục Lương và phụ cấp.

### Feature: shift_schedule

Question: LG Display làm ca nào?

Answer: Công nhân làm ca ngày hoặc ca đêm theo sắp xếp của nhà máy; ca thường kéo
dài khoảng 12 tiếng bao gồm thời gian nghỉ theo quy định.

Source: Tin tuyển dụng LG Display, mục Thời gian làm việc.

### Feature: overtime_rate

Question: Tăng ca tính tiền thế nào?

Answer: Tăng ca được tính theo quy định hiện hành và được cộng vào thu nhập thực tế
hàng tháng.

Source: Tin tuyển dụng LG Display, mục Tăng ca.

### Feature: housing

Question: Ở xa có chỗ ở không?

Answer: Ứng viên ở xa có thể hỏi admin VFIC để được tư vấn khu trọ hoặc phương án
lưu trú phù hợp gần khu công nghiệp.

Source: Tin tuyển dụng LG Display, mục Hỗ trợ ứng viên.

### Feature: job_difficulty

Question: Công việc LG Display làm gì?

Answer: Công việc chính là sản xuất, kiểm tra và hỗ trợ dây chuyền màn hình; không
yêu cầu kinh nghiệm vì ứng viên được hướng dẫn trước khi vào ca.

Source: Tin tuyển dụng LG Display, mục Công việc.

### Feature: commute_support

Question: Có xe đưa đón không?

Answer: Có xe đưa đón theo tuyến cố định; ứng viên cần kiểm tra đúng điểm đón và
có mặt sớm hơn giờ xe chạy.

Source: Tin tuyển dụng LG Display, mục Xe đưa đón.

### Feature: application_simplicity

Question: Cần chuẩn bị hồ sơ gì?

Answer: Ứng viên chỉ cần CCCD gốc và 2 ảnh 4x6; VFIC hỗ trợ làm hồ sơ miễn phí.

Source: Tin tuyển dụng LG Display, mục Note.

### Feature: joining_bonus

Question: Có thưởng khi đi làm không?

Answer: Thưởng đi làm tùy chương trình tuyển dụng từng thời điểm; nếu nguồn hiện tại
không ghi rõ, admin VFIC cần xác nhận trước khi tư vấn số tiền cụ thể.

Source: Tin tuyển dụng LG Display, mục Thưởng.

### Feature: daily_cost_benefits

Question: Công ty hỗ trợ chi phí ăn ở, đi lại gì?

Answer: Ứng viên được tư vấn xe đưa đón, hỗ trợ hồ sơ miễn phí và các phụ cấp liên
quan theo chính sách đang hiệu lực.

Source: Tin tuyển dụng LG Display, mục Phúc lợi.

## Rules/Policies

### Rule: Bus pickup time

IF:
- A worker asks when to arrive at a bus stop

THEN:
- Tell the worker to arrive 5 minutes before the scheduled pickup time

EXCEPT:
- If the stop has no scheduled time in the source, tell the worker VFIC needs to confirm

ESCALATE:
- The worker reports conflicting bus times
- The route is missing from the route table

## FAQ

### FAQ: Does VFIC pay weekly?

Question: VFIC có trả lương theo tuần không?

Answer: Có. VFIC có chương trình trả lương theo tuần cho ứng viên LG Display.

Applies to:
- LG Display temporary workers
- Payroll questions

Escalate when:
- The worker asks about a specific unpaid salary amount
- The worker disputes a payment

## Contacts

### Contact: Training day admin

Purpose: Hỗ trợ ứng viên trong buổi đào tạo đầu tiên.

Contact: Admin Mai

Phone: 0868232891

## Bus Routes

### Bus Route: TD Plaza day outbound

route_id: td_plaza_day_outbound
route_group: TD Plaza
route_name: TD Plaza
route_no: "01"
route_variant: "1"
shift: day
direction: outbound
area: Hai Phong
mode: standard
notes: Workers must be at the pickup point 5 minutes early.

service_days:
- mon_thu: outbound_admin_and_day=A, return_night=M, return_admin=A, outbound_night=M, return_day=A
- fri: outbound_admin_and_day=A, return_night=M, return_admin=A, outbound_night=M, return_day=A
- sat: outbound_admin_and_day=M, return_night=M, return_admin=M, outbound_night=M, return_day=M
- sun: outbound_admin_and_day=M, return_night=M, return_admin=M, outbound_night=M, return_day=M

| stop_order | stop_name | aliases | scheduled_time | notes |
|---|---|---|---|---|
| 1 | TD Plaza | TD Plaza | 06:15 | Main pickup point |
| 2 | LGD | LG Display |  | Destination; no arrival time in source |
