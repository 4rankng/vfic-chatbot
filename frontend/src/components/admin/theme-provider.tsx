import { useEffect } from "react";

import {
  ThemeProviderContext,
  type Theme,
  type ThemeProviderState,
} from "./theme-context";

type ThemeProviderProps = {
  children: React.ReactNode;
  defaultTheme?: Theme;
  storageKey?: string;
};

const LIGHT_THEME_STATE: ThemeProviderState = {
  theme: "light",
  setTheme: () => undefined,
};

/** Light-only product theme provider. */
export function ThemeProvider({ children }: ThemeProviderProps) {
  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove("dark");
    root.classList.add("light");
    root.dataset.theme = "tingting";
  }, []);

  return (
    <ThemeProviderContext.Provider value={LIGHT_THEME_STATE}>
      {children}
    </ThemeProviderContext.Provider>
  );
}
