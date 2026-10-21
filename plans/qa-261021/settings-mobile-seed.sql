-- Evidence seed for qa/2026-10-21-settings-mobile (dev DB, idempotent).
-- Three stored transcripts + inspected-day markers so the viewer's card list
-- has rows to tap WITHOUT calling the Cloudfone vendor API (the marker's
-- "checked" status suppresses the on-demand day fetch).
INSERT INTO cloudfone_call_transcripts
  (call_id, day, started_at, caller, talk_seconds, transcript, created_at)
VALUES
  (
    '1790848955',
    '2026-10-21',
    '2026-10-21T09:15:11',
    '0362698948',
    98,
    'S1: Tổng đài TinhTing, em nghe ạ.
S2: Alo, cho em hỏi bên mình đang tuyển vị trí nhân viên kho đúng không ạ?
S1: Dạ đúng rồi chị. Bên em đang tuyển nhân viên kho cho dự án Bình Dương, lương từ 12 triệu.
S2: Vậy cho em hỏi ca làm việc như thế nào ạ?
S1: Dạ bên em làm ca 8 tiếng, có tăng ca tính theo lương quy định của nhà nước.
S2: Em muốn ứng tuyển thì liên hệ ai ạ?
S1: Chị để lại số điện thoại, nhân viên bên em sẽ gọi tư vấn kỹ cho chị trong hôm nay nhé.
S2: Dạ em cảm ơn ạ.',
    now()
  ),
  (
    '1790818523',
    '2026-10-21',
    '2026-10-21T14:30:00',
    '0902065233',
    45,
    'S1: Dạ em nghe ạ.
S2: Cho em hỏi giá dịch vụ bên mình.
S1: Dạ anh quan tâm gói nào ạ? Bên em có gói cơ bản và gói doanh nghiệp.
S2: Để em cân nhắc sau.',
    now()
  ),
  (
    '1790790011',
    '2026-10-20',
    '2026-10-20T10:05:47',
    '0912345678',
    212,
    'S1: Công ty TinhTing xin nghe.
S2: Em muốn ứng tuyển lái xe ạ, bên mình còn tuyển không?
S1: Dạ còn anh. Vị trí lái xe bằng B2, chạy tuyến nội thành, lương 15 triệu.
S2: Thời gian phỏng vấn khi nào?
S1: Dạ sáng thứ Hai tuần sau anh qua văn phòng nhé, cần mang theo bằng lái và CMND.',
    now()
  )
ON CONFLICT (call_id) DO NOTHING;

INSERT INTO cloudfone_transcript_days
  (day, status, call_count, recordable_count, transcript_count, error, checked_at)
VALUES
  ('2026-10-21', 'checked', 2, 2, 2, NULL, now()),
  ('2026-10-20', 'checked', 1, 1, 1, NULL, now())
ON CONFLICT (day) DO NOTHING;
