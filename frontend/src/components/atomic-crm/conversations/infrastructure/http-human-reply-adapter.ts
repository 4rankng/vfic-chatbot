import {
  type HumanReplyServicePort,
  retryHumanReply,
  sendHumanReply,
} from "@/lib/vfic/humanReplyService";

export const httpHumanReplyAdapter: HumanReplyServicePort = {
  send: sendHumanReply,
  retry: retryHumanReply,
};
