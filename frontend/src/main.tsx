import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import { LanguageRoot, initLanguage } from "./lib/i18n";
import { initTheme } from "./lib/theme";
import "@fontsource-variable/inter/wght.css";
import "./styles.css";

initTheme();
initLanguage();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <LanguageRoot>
          <App />
        </LanguageRoot>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
