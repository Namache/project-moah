import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UpdateBanner } from "./UpdateBanner";

const renderBanner = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><UpdateBanner /></QueryClientProvider>);
const status = (newer: boolean) => vi.fn(async () => Response.json({ running: "0.3.0+old", newer, installed: newer ? "0.3.1+new" : null }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("update banner", () => {
  it("stays out of the way while the running version is the newest", async () => {
    vi.stubGlobal("fetch", status(false));
    renderBanner();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("offers a restart after an update, and Restart now asks the desktop app for it", async () => {
    const restartForUpdate = vi.fn(async () => true);
    vi.stubGlobal("projectBrainDesktop", { apiToken: "t", restartForUpdate });
    vi.stubGlobal("fetch", status(true));
    renderBanner();
    expect(await screen.findByText("Project Moah was updated. Restart it to use the new version.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Restart now" }));
    expect(restartForUpdate).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Restarting…" })).toHaveProperty("disabled", true);
  });

  it("in a browser says how to restart, and Later hides it", async () => {
    vi.stubGlobal("fetch", status(true));
    renderBanner();
    expect(await screen.findByText("Project Moah was updated. Close it and open it again to use the new version.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Restart now" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Later" }));
    expect(screen.queryByRole("status")).toBeNull();
  });
});
