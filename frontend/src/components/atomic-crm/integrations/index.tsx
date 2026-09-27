import { lazy } from "react";
import { KeyRound } from "lucide-react";

const SettingsConsolePage = lazy(() =>
  import("./SettingsConsolePage").then((m) => ({
    default: m.SettingsConsolePage,
  })),
);

export default {
  list: SettingsConsolePage,
  icon: KeyRound,
};
