import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentSync } from "./components/AgentSync";

const folders = [
  { folder: "/home/me/Desktop/Trailhead", status: "suggested", project_id: "p1", project_name: "Trailhead", claude_sessions: 3, codex_sessions: 1, last_seen: null },
  { folder: "/home/me/Desktop/Noise", status: "ignored", project_id: null, project_name: null, claude_sessions: 1, codex_sessions: 0, last_seen: null },
];

function setup() {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    calls.push({ url: String(input), method: options?.method ?? "GET", body: options?.body ? JSON.parse(String(options.body)) : undefined });
    return Response.json({ created: [], suggested: [], folders });
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><AgentSync /></MemoryRouter></QueryClientProvider>);
  return calls;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("sync from agents", () => {
  it("asks before matching a folder to an existing project", async () => {
    const calls = setup();
    expect(await screen.findByText("Is this Trailhead's folder?")).toBeInTheDocument();
    expect(screen.getAllByText("~/Desktop/Trailhead").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Yes, it is Trailhead" }));
    expect(calls.at(-1)).toMatchObject({ url: "/api/agent-folders/decide", method: "POST", body: { folder: "/home/me/Desktop/Trailhead", action: "link", project_id: "p1" } });
    await userEvent.click(screen.getByRole("button", { name: "No, make a new project" }));
    expect(calls.at(-1)?.body).toMatchObject({ action: "create" });
  });

  it("lists found folders and can bring an ignored one back", async () => {
    const calls = setup();
    await userEvent.click(await screen.findByText("2 folders found"));
    const list = screen.getByRole("list");
    expect(within(list).getByText("Ignored")).toBeInTheDocument();
    await userEvent.click(within(list).getByRole("button", { name: "Make a project" }));
    expect(calls.at(-1)?.body).toMatchObject({ folder: "/home/me/Desktop/Noise", action: "create" });
  });
});
