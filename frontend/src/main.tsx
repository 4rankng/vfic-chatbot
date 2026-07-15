import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import "./flat-surfaces.css";
import App from "./App.tsx";
import { InstallationBootstrap } from "@/components/atomic-crm/installation/InstallationBootstrap";

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

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <InstallationBootstrap>
      <App />
    </InstallationBootstrap>
  </StrictMode>,
);
