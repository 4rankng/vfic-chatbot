import { UserList } from "../users/UserList";
import { FacebookMessengerIntegrationPage } from "./FacebookMessengerIntegrationPage";

/**
 * The settings console embeds two pages owned by other products (users,
 * Messenger). Each keeps its own route there and is mounted here from a
 * thin section, so the settings navigation stays as it is.
 */

export const UsersSettingsSection = () => (
  <section className="settings-embedded-resource settings-embedded-users">
    <UserList embedded />
  </section>
);

export const MessengerSettingsSection = () => (
  <FacebookMessengerIntegrationPage />
);
