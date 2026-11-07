import { systemApi } from "../api/system";

const MAX_REPORTS = 20;

/**
 * Uncaught errors in the window go to the local error log (Settings > Diagnostics), through the
 * app's own local service. Each distinct message is sent once, and at most a few per session, so
 * an error that repeats on every frame cannot flood the log.
 */
export function initErrorReporting(target: Window = window, report = systemApi.reportError): void {
  const seen = new Set<string>();
  const send = (message: string, detail: string) => {
    if (!message || seen.has(message) || seen.size >= MAX_REPORTS) return;
    seen.add(message);
    report(message.slice(0, 4_000), detail.slice(0, 20_000)).catch(() => { /* the service may be stopping */ });
  };
  target.addEventListener("error", (event) => {
    const error = event.error instanceof Error ? event.error : null;
    send(error ? `${error.name}: ${error.message}` : String(event.message ?? ""), error?.stack ?? (event.filename ? `${event.filename}:${event.lineno}:${event.colno}` : ""));
  });
  target.addEventListener("unhandledrejection", (event) => {
    const reason: unknown = event.reason;
    // Failed requests are already shown where they happen; only bugs are worth logging.
    if (reason instanceof Error && reason.name === "ApiError") return;
    send(reason instanceof Error ? `${reason.name}: ${reason.message}` : `Unhandled rejection: ${String(reason)}`, reason instanceof Error ? reason.stack ?? "" : "");
  });
}
