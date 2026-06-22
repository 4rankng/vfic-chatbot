import { random } from "faker/locale/en_US";

import type { Conversation, Message } from "../../../types";
import type { Db } from "./types";

const AI_GREETINGS = [
  "Xin chào! VFIC có thể hỗ trợ gì cho bạn?",
  "Chào bạn, mình là trợ lý ảo của VFIC. Bạn đang tìm việc ở lĩnh vực nào?",
  "Hi! Cảm ơn bạn đã liên hệ VFIC. Bạn có thể chia sẻ thêm về mong muốn công việc không?",
  "Chào bạn! Bạn quan tâm đến vị trí nào của VFIC?",
];

const CANDIDATE_REPLIES = [
  "Mình đang tìm việc frontend React, lương khoảng 1500 USD.",
  "Có vị trí backend không bạn? Mình có 3 năm kinh nghiệm Node.js.",
  "Mình muốn ứng tuyển vị trí Senior Frontend.",
  "Bao giờ có thể phỏng vấn vậy bạn?",
  "Mình gửi CV nhé.",
  "Cảm ơn bạn, mình sẽ tìm hiểu thêm.",
];

const RECRUITER_REPLIES = [
  "Cảm ơn bạn, mình sẽ gửi JD cho bạn trong ít phút.",
  "Bạn có thể gửi CV qua email này nhé.",
  "Lịch phỏng vấn dự kiến vào thứ 5 tuần sau, bạn confirm giúp mình.",
  "Mình sẽ chuyển CV cho team lead review.",
];

export const generateMessages = (db: Db, perConv = 12): Message[] => {
  const conversations = db.conversations ?? [];
  const messages: Message[] = [];

  conversations.forEach((conv: Conversation, convIdx: number) => {
    let idCounter = 0;
    let timestamp = new Date(conv.created_at);

    // Alternate: candidate, ai, candidate, recruiter (if human), etc.
    for (let i = 0; i < perConv; i++) {
      timestamp = new Date(
        timestamp.getTime() +
          1000 * 60 * (5 + random.number({ min: 0, max: 30 })),
      );

      let type: "inbound" | "outbound" | "system" = "inbound";
      let content = "";
      const data: Record<string, any> = {};

      if (i === 0) {
        content = random.arrayElement(AI_GREETINGS);
        type = "outbound";
        data.ai = true;
      } else if (i % 3 === 1) {
        content = random.arrayElement(CANDIDATE_REPLIES);
        type = "inbound";
      } else if (i % 3 === 2 && conv.mode === "human") {
        content = random.arrayElement(RECRUITER_REPLIES);
        type = "outbound";
        data.recruiter_id = "recruiter-1";
      } else {
        content = random.arrayElement(AI_GREETINGS);
        type = "outbound";
        data.ai = true;
      }

      messages.push({
        id: `msg-${convIdx}-${idCounter++}`,
        zalo_message_id: `zmsg-${convIdx}-${idCounter}`,
        conversation_id: conv.id,
        type,
        content,
        data,
        created_at: timestamp.toISOString(),
      });
    }
  });

  return messages;
};
