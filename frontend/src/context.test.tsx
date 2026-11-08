import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const project = { id: "p1", name: "Trailhead", slug: "c", description: null, icon: null, accent: null, root_path: null, status: "active", current_focus_task_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_opened_at: null, archived_at: null };
const pack = (detail: string, over = {}) => ({ project_id: "p1", project_name: "Trailhead", task: "CAMP-001", detail_level: detail, budget: 1500, estimated_tokens: detail === "minimal" ? 300 : 900, over_budget: false, text: `PACK ${detail}`, sections: [{ key: "task", title: "Current Task", tokens: 100, items: 1 }, { key: "decisions", title: "Important Decisions", tokens: 200, items: 2 }], items: [], omitted: { hidden: 2, "manual only": 1 }, warnings: [], ...over });

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("AI context inspector", () => {
  it("previews each detail level as an agent gets it, with the brief's size, and includes manual-only memory on request", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/projects?")) return Response.json([project]);
      if (url === "/api/projects/p1") return Response.json(project);
      if (url.startsWith("/api/projects/p1/context")) return Response.json(pack(new URL(url, "http://x").searchParams.get("detail") ?? "balanced", { brief_tokens: 2400, warnings: ["No task was given and no current focus is set; this is a project overview."] }));
      if (url.startsWith("/api/projects/p1/memory")) return Response.json([{ id: "m1", human_id: "NOTE-001", title: "Manual party note", type: "note" }]);
      return Response.json([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={["/projects/p1/context"]}><App /></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByText(/about 900 tokens/)).toBeInTheDocument();
    expect(screen.getByText(/about 2,400 tokens/)).toBeInTheDocument();
    // Only what is needed is on the page; the rest waits under "?".
    expect(screen.queryByText(/Left out/)).not.toBeInTheDocument();
    expect(screen.queryByText(/no current focus is set/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Adds rules, known issues/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Help: about this pack" }));
    expect(screen.getByText(/no current focus is set/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Help: Balanced" }));
    expect(screen.getByText(/Adds rules, known issues/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([u]) => !String(u).startsWith("/api/projects/p1/context") || String(u).includes("agent=true"))).toBe(true);
    await user.click(screen.getByRole("radio", { name: /Minimal/ }));
    expect(await screen.findByText(/about 300 tokens/)).toBeInTheDocument();
    await user.click(await screen.findByRole("checkbox", { name: /NOTE-001/ }));
    await screen.findByText(/about 300 tokens/);
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("include=NOTE-001") && String(u).includes("detail=minimal"))).toBe(true);
    await user.click(screen.getByRole("button", { name: "Preview context" }));
    expect(screen.getByLabelText("Context preview")).toHaveTextContent("PACK minimal");
  });
  it("says when the pack's task was picked automatically, so the picker and the result never disagree", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/projects?")) return Response.json([project]);
      if (url === "/api/projects/p1") return Response.json(project);
      if (url.startsWith("/api/projects/p1/context")) return Response.json(pack("balanced", { task: "CAMP-001", warnings: ["No task was given; it is the task in progress, so it was used. Pass task= for another."] }));
      return Response.json([]);
    }));
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={["/projects/p1/context"]}><App /></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByRole("heading", { name: /Context for CAMP-001, picked automatically/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Automatic (the agent's pick)" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /No task/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Help: about this pack" }));
    expect(screen.getByText(/Moah picked the unfinished task an agent would continue/)).toBeInTheDocument();
  });
});
