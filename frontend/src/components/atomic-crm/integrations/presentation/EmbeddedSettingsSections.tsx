import { PersonaList } from "../../personas/PersonaList";
import { UserList } from "../../users/UserList";
import { FacebookMessengerIntegrationPage } from "../FacebookMessengerIntegrationPage";

/**
 * The settings console embeds three pages owned by other products (personas,
 * users, Messenger). Each keeps its own route there and is mounted here from a
 * thin section, so the settings navigation stays as it is.
 */

export const AgentsSettingsSection = () => (
  <section className="settings-embedded-resource">
    <PersonaList embedded />
  </section>
);

export const UsersSettingsSection = () => (
  <section className="settings-embedded-resource settings-embedded-users">
    <UserList embedded />
  </section>
);

export const MessengerSettingsSection = () => (
  <FacebookMessengerIntegrationPage />
);
