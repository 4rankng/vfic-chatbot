import {
  Bot,
  Brain,
  KeyRound,
  Mail,
  MapPin,
  MessageCircle,
  MessagesSquare,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

/**
 * Settings navigation: the eight entries of the console rail and the header
 * copy each one shows. Kept free of JSX so the rail, the mobile drawer and the
 * header all read one source.
 */

export type SettingsItemId =
  | "settings-zalo-channel"
  | "settings-facebook-messenger"
  | "settings-llm-providers"
  | "settings-jev"
  | "settings-tingting"
  | "settings-email-digest"
  | "settings-geocoder"
  | "settings-users";

export type SettingsSectionNavItem = {
  itemId: SettingsItemId;
  label: string;
  description: string;
  Icon: LucideIcon;
};

export const SETTINGS_NAV_ITEMS: SettingsSectionNavItem[] = [
  {
    itemId: "settings-zalo-channel",
    label: "Zalo",
    description: "Bot Platform và OA",
    Icon: MessageCircle,
  },
  {
    itemId: "settings-facebook-messenger",
    label: "Messenger",
    description: "Trang Facebook",
    Icon: MessagesSquare,
  },
  {
    itemId: "settings-llm-providers",
    label: "AI Providers",
    description: "Mặc định & dự phòng",
    Icon: Bot,
  },
  {
    itemId: "settings-jev",
    label: "Jev",
    description: "Mô hình quyết định",
    Icon: Brain,
  },
  {
    itemId: "settings-tingting",
    label: "TingTing",
    description: "Đặt lại mật khẩu",
    Icon: KeyRound,
  },
  {
    itemId: "settings-email-digest",
    label: "Email ứng viên",
    description: "Gửi ứng viên mới qua email",
    Icon: Mail,
  },
  {
    itemId: "settings-geocoder",
    label: "Geocoder",
    description: "Khoảng cách dự án",
    Icon: MapPin,
  },
  {
    itemId: "settings-users",
    label: "Người dùng",
    description: "Tài khoản & quyền",
    Icon: UsersRound,
  },
];

export const SETTINGS_VIEW_COPY: Record<
  SettingsItemId,
  { kicker: string; title: string; description: string }
> = {
  "settings-zalo-channel": {
    kicker: "Kênh liên lạc",
    title: "Zalo",
    description: "Bot Platform và OA cho tin nhắn Zalo.",
  },
  "settings-facebook-messenger": {
    kicker: "Kênh liên lạc",
    title: "Messenger",
    description: "Kết nối Trang Facebook để nhắn tin với ứng viên.",
  },
  "settings-llm-providers": {
    kicker: "Nhà cung cấp AI",
    title: "AI Providers",
    description:
      "Chọn một nhà cung cấp mặc định. Khi hết quota, hệ thống tự chuyển sang nhà cung cấp còn lại theo thứ tự bên dưới.",
  },
  "settings-jev": {
    kicker: "Nhà cung cấp AI",
    title: "Jev",
    description: "Mô hình quyết định System One cho bot.",
  },
  "settings-tingting": {
    kicker: "Tích hợp",
    title: "TingTing · Đặt lại mật khẩu",
    description:
      "API key dùng để tra cứu nhân sự và gửi OTP đặt lại mật khẩu qua TingTing.",
  },
  "settings-email-digest": {
    kicker: "Tích hợp",
    title: "Danh sách ứng viên mới",
    description:
      "Gửi định kỳ email danh sách ứng viên mới (Zalo chatbot, Messenger, OA khác — không gồm TingTing OA) với số điện thoại, dự án quan tâm và tóm tắt hội thoại.",
  },
  "settings-geocoder": {
    kicker: "Tích hợp",
    title: "Geocoder · Khoảng cách dự án",
    description:
      "Khoá geocoder dùng để tính khoảng cách từ nơi ứng viên nêu đến từng dự án.",
  },
  "settings-users": {
    kicker: "Không gian cài đặt",
    title: "Người dùng",
    description: "Tài khoản nội bộ và quyền quản trị.",
  },
};

const FACEBOOK_OAUTH_CALLBACK_KEYS = [
  "facebook_oauth_status",
  "facebook_oauth_flow_id",
  "facebook_oauth_error",
] as const;

/**
 * The OAuth callback returns to the settings hash; landing on Messenger then
 * means the operator sees the Page picker instead of hunting for the section.
 */
export const resolveInitialSettingsItemId = (): SettingsItemId => {
  if (typeof window === "undefined") return "settings-zalo-channel";

  const queryIndex = window.location.hash.indexOf("?");
  if (queryIndex === -1) return "settings-zalo-channel";

  const params = new URLSearchParams(
    window.location.hash.slice(queryIndex + 1),
  );
  return FACEBOOK_OAUTH_CALLBACK_KEYS.some((key) => params.has(key))
    ? "settings-facebook-messenger"
    : "settings-zalo-channel";
};
