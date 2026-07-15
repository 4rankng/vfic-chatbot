import { Notification } from "@/components/admin/notification";
import { useTranslate } from "ra-core";

export const ConfirmationRequired = () => {
  const translate = useTranslate();

  return (
    <div className="h-screen p-8">
      <h1 className="text-xl font-semibold">Xác nhận tài khoản</h1>
      <div className="h-full text-center">
        <div className="max-w-sm mx-auto h-full flex flex-col justify-center gap-4">
          <h1 className="text-page-title font-bold mb-4">
            {translate("crm.auth.welcome_title", {
              _: "Kiểm tra email của bạn",
            })}
          </h1>
          <p className="text-base mb-4">
            {translate("crm.auth.confirmation_required", {
              _: "Mở liên kết vừa được gửi qua email để xác nhận tài khoản.",
            })}
          </p>
        </div>
      </div>
      <Notification />
    </div>
  );
};

ConfirmationRequired.path = "/sign-up/confirm";
