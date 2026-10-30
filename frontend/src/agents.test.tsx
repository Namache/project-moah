import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentSettingsCard } from "./components/AgentSettingsCard";
import { ProjectsNav } from "./components/ProjectsNav";
import { WorkOnTaskButton } from "./components/tasks/WorkOnTaskButton";
import type { Project } from "./types/project";

const settings = { default_agent: "codex", second_opinion_enabled: false, codex_command: "codex", claude_command: "claude" };
const prompt = { agent: "codex", task: "CAMP-001", prompt: "Work on task CAMP-001", url: "codex://new?prompt=Work", folder: "/home/me/game" };

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}
function mockFetch() {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input);
    calls.push({ url, method: options?.method ?? "GET", body: options?.body ? JSON.parse(String(options.body)) : undefined });
    if (url.includes("/work-prompt")) return Response.json(url.includes("agent=claude") ? { ...prompt, agent: "claude", url: "claude://code/new?q=Work" } : prompt);
    if (options?.method === "PATCH") return Response.json({ ...settings, ...JSON.parse(String(options.body)) });
    return Response.json(settings);
  }));
  return calls;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); delete (window as { projectBrainDesktop?: unknown }).projectBrainDesktop; });

describe("work on task", () => {
  it("opens the default agent with the prompt and copies it", async () => {
    const calls = mockFetch();
    const openAgent = vi.fn(async () => true);
    (window as { projectBrainDesktop?: unknown }).projectBrainDesktop = { apiToken: "t", openAgent };
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    wrap(<WorkOnTaskButton projectId="p1" task="CAMP-001" />);
    await userEvent.click(await screen.findByRole("button", { name: "Work on task in Codex" }));
    expect(calls.some((c) => c.url === "/api/projects/p1/tasks/CAMP-001/work-prompt?agent=codex")).toBe(true);
    expect(openAgent).toHaveBeenCalledWith("codex://new?prompt=Work");
    expect(writeText).toHaveBeenCalledWith("Work on task CAMP-001");
    expect(await screen.findByText(/Codex opened with the prompt typed in/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "or in Claude" }));
    expect(openAgent).toHaveBeenLastCalledWith("claude://code/new?q=Work");
  });

  it("says so when the app cannot be opened", async () => {
    mockFetch();
    wrap(<WorkOnTaskButton projectId="p1" task="CAMP-001" compact />);
    await userEvent.click(await screen.findByRole("button", { name: "Work on task in Codex" }));
    expect(await screen.findByText(/could not be opened from here/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /or in/ })).toBeNull();
  });
});

describe("agent settings", () => {
  it("changes the default agent and switches second opinions on", async () => {
    const calls = mockFetch();
    wrap(<AgentSettingsCard />);
    await userEvent.click(await screen.findByRole("button", { name: "Claude" }));
    expect(calls.at(-1)).toMatchObject({ method: "PATCH", body: { default_agent: "claude" } });
    await userEvent.click(screen.getByRole("checkbox", { name: /Allow second opinions/ }));
    expect(calls.at(-1)?.body).toEqual({ second_opinion_enabled: true });
  });

  it("keeps an unsaved command while another setting is saved, then saves it", async () => {
    const user = userEvent.setup();
    const calls = mockFetch();
    wrap(<AgentSettingsCard />);
    const codex = await screen.findByRole("textbox", { name: "Command for Codex" });
    await user.clear(codex);
    await user.type(codex, "distrobox enter dev -- codex");
    await user.click(screen.getByRole("button", { name: "Claude" }));
    await vi.waitFor(() => expect(calls.at(-1)).toMatchObject({ method: "PATCH", body: { default_agent: "claude" } }));
    expect(screen.getByRole("textbox", { name: "Command for Codex" })).toHaveValue("distrobox enter dev -- codex");
    await user.click(screen.getByRole("button", { name: "Save commands" }));
    await vi.waitFor(() => expect(calls.at(-1)?.body).toEqual({ codex_command: "distrobox enter dev -- codex", claude_command: "claude" }));
  });
});

describe("projects in the sidebar", () => {
  const p = (id: string, name: string, opened: string): Project => ({ id, name, slug: id, description: null, icon: null, accent: null, root_path: null, status: "active", current_focus_task_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_opened_at: opened, archived_at: null } as unknown as Project);
  const projects = [p("a", "Older", "2026-01-01T00:00:00Z"), p("b", "Recent", "2026-02-01T00:00:00Z")];

  it("lists every project, most recent first, and remembers when it is closed", async () => {
    wrap(<ProjectsNav projects={projects} pending={{ a: 2 }} wide currentId="" />);
    const list = screen.getByRole("navigation", { name: "Your projects" });
    expect(within(list).getAllByRole("link").map((l) => l.textContent)).toEqual(["Recent", "Older2", "All projects"]);
    await userEvent.click(screen.getByRole("button", { name: "Hide project list" }));
    expect(screen.queryByRole("navigation", { name: "Your projects" })).toBeNull();
    expect(localStorage.getItem("pb-sidebar-projects-open")).toBe("0");
  });

  it("opens as a pop-out from the icon rail", async () => {
    wrap(<ProjectsNav projects={projects} pending={{}} wide={false} currentId="" />);
    expect(screen.queryByRole("navigation", { name: "Your projects" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Projects" }));
    expect(screen.getByRole("navigation", { name: "Your projects" })).toBeInTheDocument();
  });
});

describe("sidebar width", () => {
  it("resizes with the keyboard within limits and remembers it", async () => {
    const { SidebarResizer, useSidebarWidth } = await import("./components/SidebarResizer");
    function Harness() { const [w, set] = useSidebarWidth(); return <SidebarResizer width={w} onResize={set} />; }
    render(<Harness />);
    const handle = screen.getByRole("separator", { name: "Resize sidebar" });
    expect(handle).toHaveAttribute("aria-valuenow", "256");
    handle.focus();
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    expect(handle).toHaveAttribute("aria-valuenow", "288");
    expect(localStorage.getItem("pb-sidebar-width")).toBe("288");
    for (let i = 0; i < 20; i++) await userEvent.keyboard("{ArrowLeft}");
    expect(handle).toHaveAttribute("aria-valuenow", "200");
    await userEvent.keyboard("{End}");
    expect(handle).toHaveAttribute("aria-valuenow", "440");
    await userEvent.dblClick(handle);
    expect(handle).toHaveAttribute("aria-valuenow", "256");
  });
});
