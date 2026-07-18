import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import "./flat-surfaces.css";
import App from "./App.tsx";
import { InstallationBootstrap } from "@/components/atomic-crm/installation/InstallationBootstrap";
import { registerSW } from "virtual:pwa-register";

// After a new deploy, the service worker may replace its pre-cache while
// the page still holds old chunk references. A reload picks up the new
// HTML + new SW cache. A sessionStorage guard prevents infinite loops.
// See https://vite.dev/guide/build.html#load-error-handling
window.addEventListener("vite:preloadError", () => {
  const key = "chunk-reload";
  if (!sessionStorage.getItem(key)) {
    sessionStorage.setItem(key, "1");
    window.location.reload();
  }
});

// Use vite-plugin-pwa's Workbox registration instead of the generated bare
// registration script. In auto-update mode this reloads an open tab when a new
// service worker takes control, so a deployed UI cannot keep running an old
// application bundle until the user discovers that a hard refresh is needed.
registerSW({ immediate: true });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <InstallationBootstrap>
      <App />
    </InstallationBootstrap>
  </StrictMode>,
);
