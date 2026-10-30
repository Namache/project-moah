import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const projects = ["p1", "p2"].map((id, i) => ({ id, name: i ? "Starling" : "Trailhead", slug: id, description: null, icon: null, accent: null, root_path: null, status: "active", current_focus_task_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_opened_at: null, archived_at: null }));
const hit = (over = {}) => ({ entity_type: "memory", entity_id: "m1", project_id: "p1", project_name: "Trailhead", human_id: "DEC-001", title: "Party size is 5", snippet: "Five folk per party", status: "active", memory_type: "decision", score: 1, updated_at: null, ...over });

function mock(onSearch: (url: string) => unknown[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith("/api/projects?")) return Response.json(projects);
    if (/^\/api\/projects\/p\d$/.test(url)) return Response.json(projects.find((p) => url.endsWith(p.id)));
    if (url.includes("search?")) { const items = onSearch(url); return Response.json({ items, total: items.length, limit: 25, offset: 0 }); }
    return Response.json([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
const renderAt = (path: string) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("search", () => {
  it("searches the current project first and links to the record", async () => {
    const fetchMock = mock(() => [hit()]);
    renderAt("/search?q=party&project=p1");
    const link = await screen.findByRole("link", { name: /Party size is 5/ });
    expect(link).toHaveAttribute("href", "/projects/p1/memory?memory=DEC-001");
    expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/projects/p1/search?q=party"))).toBe(true);
    expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/search?"))).toBe(false);
  });

  it("searches all projects only after an explicit choice, and names each project", async () => {
    const user = userEvent.setup();
    const fetchMock = mock((url) => (url.startsWith("/api/search?") ? [hit(), hit({ entity_id: "m2", project_id: "p2", project_name: "Starling", title: "Party size is 4", human_id: "DEC-002" })] : [hit()]));
    renderAt("/search?q=party&project=p1");
    await screen.findByRole("link", { name: /Party size is 5/ });
    await user.click(screen.getByRole("button", { name: "All projects" }));
    const second = await screen.findByRole("link", { name: /Party size is 4/ });
    expect(within(second).getByText("Starling")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/search?q=party"))).toBe(true);
  });

  it("opens Global rules found in an all-projects search on the Global page", async () => {
    mock(() => [hit({ project_id: "global", project_name: "Global rules", human_id: "RULE-001", title: "Always write tests", memory_type: "rule" })]);
    renderAt("/search?q=tests");
    expect(await screen.findByRole("link", { name: /Always write tests/ })).toHaveAttribute("href", "/global?memory=RULE-001");
  });

  it("filters by type, offers history, and explains empty results", async () => {
    const user = userEvent.setup();
    const fetchMock = mock(() => []);
    renderAt("/search?q=zzz&project=p1");
    expect(await screen.findByText('No results for "zzz"')).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Memory" }));
    await user.click(screen.getByRole("checkbox", { name: /archived and history/ }));
    await screen.findByRole("combobox", { name: "Memory type" });
    const last = String(fetchMock.mock.calls.at(-1)?.[0]);
    expect(last).toContain("entity_type=memory");
    expect(last).toContain("include_archived=true");
  });

  it("applies a memory type and clears it when switching to another type", async () => {
    const user = userEvent.setup();
    const fetchMock = mock(() => []);
    renderAt("/search?q=zzz&project=p1&type=memory");
    await user.selectOptions(await screen.findByRole("combobox", { name: "Memory type" }), "decision");
    await vi.waitFor(() => expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("memory_type=decision"));
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("entity_type=memory");
    await user.click(screen.getByRole("button", { name: "Tasks" }));
    await vi.waitFor(() => expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("entity_type=task"));
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).not.toContain("memory_type");
    expect(screen.queryByRole("combobox", { name: "Memory type" })).not.toBeInTheDocument();
  });

  it("searches the current project from the command palette", async () => {
    const user = userEvent.setup();
    mock(() => [hit({ entity_type: "task", human_id: "CAMP-001", title: "Camp capacity", memory_type: null })]);
    renderAt("/projects/p1");
    await screen.findByRole("heading", { name: "Trailhead" });
    await user.click(screen.getByRole("button", { name: /Search or jump to/ }));
    const box = screen.getByRole("combobox", { name: "Search or jump to" });
    await user.type(box, "camp");
    expect(screen.getAllByRole("option")[0]).toHaveTextContent('Search "camp" in Trailhead');
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("link", { name: /Camp capacity/ })).toHaveAttribute("href", "/projects/p1/tasks?task=CAMP-001");
  });

  it("opens with Ctrl+K, puts a matching project first, and wraps the arrow keys", async () => {
    const user = userEvent.setup();
    mock(() => []);
    renderAt("/");
    await user.keyboard("{Control>}k{/Control}");
    await user.type(screen.getByRole("combobox", { name: "Search or jump to" }), "starl");
    const options = screen.getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Starling", 'Search "starl" in all projects']);
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { name: "Starling" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Search or jump to" })).toBeNull();
  });

  it("switches to the dark theme from the command palette", async () => {
    const user = userEvent.setup();
    mock(() => []);
    renderAt("/");
    await user.keyboard("{Control>}k{/Control}");
    await user.type(screen.getByRole("combobox", { name: "Search or jump to" }), "dark");
    expect(screen.getAllByRole("option")[0]).toHaveTextContent("Dark theme");
    await user.keyboard("{Enter}");
    expect(document.documentElement.dataset.theme).toBe("dark");
    localStorage.removeItem("pb-theme");
    document.documentElement.removeAttribute("data-theme");
  });
});
