import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BrainHealth, readHealth } from "./BrainHealth";
import type { ProjectHealth } from "../../types/graph";

const retrieval = { packs: 0, packs_recent: 0, feedback_recent: 0, through_links: null, average_depth: null, average_records: null, average_tokens: null, feedback_share: null, useful_share: null };
const project = (overrides: Partial<ProjectHealth>): ProjectHealth => ({
  id: "p1", name: "Trailhead", nodes: 40, links: 30, strong_links: 10, weak_links: 0, guessed_links: 0, memory: 40, orphans: 4, conflicts: 0, superseded: 0, shelves: 1,
  clusters: [], density: [], retrieval, checkpoints_recent: 0, ...overrides,
});

describe("readHealth", () => {
  it("calls a well linked, used and taught project good", () => {
    const reading = readHealth(project({ retrieval: { ...retrieval, packs: 30, packs_recent: 12, feedback_recent: 9 }, checkpoints_recent: 10 }));
    expect([reading.findable, reading.used, reading.learning]).toEqual([
      { tone: "good", text: "90% linked" }, { tone: "good", text: "12 packs" }, { tone: "good", text: "Feedback on 75%" },
    ]);
    expect(reading.issues).toEqual([]);
  });

  it("flags memory nothing links to, agents working without packs, and missing feedback", () => {
    const unused = readHealth(project({ orphans: 25, guessed_links: 2, checkpoints_recent: 14, retrieval: { ...retrieval, packs: 1, packs_recent: 1 } }));
    expect(unused.findable).toEqual({ tone: "attention", text: "38% linked" });
    expect(unused.used).toEqual({ tone: "attention", text: "1 pack" });
    expect(unused.issues.map((i) => i.id)).toEqual(["p1:unlinked", "p1:guesses", "p1:unused"]);
    expect(unused.issues[0].action?.to).toBe("/projects/p1/memory?review=links");

    const untaught = readHealth(project({ checkpoints_recent: 9, retrieval: { ...retrieval, packs: 20, packs_recent: 20, feedback_recent: 7 } }));
    expect(untaught.learning).toEqual({ tone: "attention", text: "Feedback on 35%" });
    expect(untaught.issues[0].text).toMatch(/after 7 of 20 packs/);
  });

  it("does not judge a project with a handful of memories", () => {
    expect(readHealth(project({ memory: 3, orphans: 3 })).findable).toEqual({ tone: "quiet", text: "0 of 3 linked" });
  });

  it("warns about Global records no agent ever gets", () => {
    const reading = readHealth(project({ id: "global", name: "Global", memory: 2, orphans: 2 }));
    expect(reading.findable).toEqual({ tone: "attention", text: "2 reach no agent" });
    expect(reading.issues[0]).toMatchObject({ project: "Global rules", action: { to: "/global?review=links" } });
  });
});

const suggestion = { key: "place:s1:bubble", kind: "place", name: "Game design > Game mechanics", message: "5 linked records about bubble sit on no shelf. File them on Game design > Game mechanics?", size: 5, members: ["memory:a", "memory:b"], records: [{ label: "WARN-001", title: "Bubble shield pops" }, { label: "WARN-002", title: "Bubble timer drifts" }], parent: null, project_id: "p1", project_name: "Trailhead" };
const pattern = { ...suggestion, key: "pattern:wyrm", kind: "pattern", name: "Wyrm", message: "5 bugs and warnings cluster around wyrm, a recurring failure area." };
const health = {
  projects: [project({
    orphans: 25, checkpoints_recent: 14, retrieval: { ...retrieval, packs: 1, packs_recent: 1, through_links: 0, average_records: 9, average_tokens: 1404 },
    clusters: [{ name: "Wyrm", size: 6, trend: "new" }],
    density: [{ shelf_id: "s1", name: "Lesson", records: 6, connected: 0.5 }],
  })],
  suggestions: [suggestion, pattern],
  last_decay: null,
  path_cache: { hits: 0, misses: 0 },
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("lists what needs a look, opens a project's details and accepts a suggested shelf", async () => {
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url.includes("/shelf-suggestions/accept")) return Response.json({ shelf_id: "s1", name: "Game mechanics" });
    if (url.endsWith("/brain/health")) return Response.json(health);
    return Response.json([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><BrainHealth /></MemoryRouter></QueryClientProvider>);

  const issues = await screen.findByRole("list", { name: "Needs a look" });
  expect(within(issues).getByText(/25 of 40 memories link to nothing/)).toBeInTheDocument();
  expect(within(issues).getByRole("link", { name: "Check them" })).toHaveAttribute("href", "/projects/p1/memory?review=links");
  expect(screen.getByText("2 things to look at")).toBeInTheDocument();

  const row = screen.getByRole("button", { name: /Trailhead.*Findable: 38% linked.*Used lately: 1 pack/ });
  await userEvent.click(row);
  expect(row).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText(/Links brought in 0% of the memories agents got/)).toBeInTheDocument();
  expect(within(screen.getByRole("list", { name: "Topics in Trailhead" })).getByText("Wyrm")).toBeInTheDocument();
  expect(screen.getByText("50% of 6")).toBeInTheDocument();

  expect(screen.getAllByText("Show the 2 memories")).toHaveLength(2);
  expect(screen.getByRole("link", { name: "Write a rule" })).toHaveAttribute("href", "/projects/p1/memory?new=1&type=rule");
  await userEvent.click(screen.getByRole("button", { name: "File them" }));
  expect(await screen.findByText("Filed on Game design > Game mechanics.")).toBeInTheDocument();
  const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/projects/p1/shelf-suggestions/accept"));
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ key: "place:s1:bubble" });
});
