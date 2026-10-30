import { expect, it } from "vitest";
import { brainDepth, brainShellPoint, buildBrainLayout, UNSHELVED } from "./layout";
import type { BrainGraph, BrainNode } from "../../types/graph";

const node = (key: string, shelves: string[] = []): BrainNode => ({ key, kind: "memory", id: key, label: key, title: key, subtype: "fact", status: "active", shelves, degree: 0 });
const centroid = (layout: ReturnType<typeof buildBrainLayout>, keys: string[]) =>
  [0, 1, 2].map((a) => keys.reduce((sum, k) => sum + layout.positions.get(k)![a], 0) / keys.length);
const distance = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

const data: BrainGraph = {
  shelves: [{ id: "s-combat", name: "Combat", parent_id: null }, { id: "s-steam", name: "Steam", parent_id: null }, { id: "s-boss", name: "Bosses", parent_id: "s-combat" }],
  nodes: [
    ...Array.from({ length: 12 }, (_, i) => node(`c${i}`, ["s-combat"])),
    ...Array.from({ length: 12 }, (_, i) => node(`s${i}`, ["s-steam"])),
    ...Array.from({ length: 6 }, (_, i) => node(`u${i}`)),
    node("b0", ["s-boss"]),
  ],
  links: [{ source: "c0", target: "c1", relationship: "relates_to", group: "knowledge", strength: 0.9, status: "active" }],
};

it("gives each shelf its own region and keeps every record inside the brain", () => {
  const layout = buildBrainLayout(data);
  const combat = centroid(layout, data.nodes.filter((n) => n.shelves[0] === "s-combat").map((n) => n.key));
  const steam = centroid(layout, data.nodes.filter((n) => n.shelves[0] === "s-steam").map((n) => n.key));
  expect(distance(combat, steam)).toBeGreaterThan(0.6);
  for (const p of layout.positions.values()) expect(brainDepth(p)).toBeLessThanOrEqual(0.9 + 1e-9);
  expect(layout.regions.get(UNSHELVED)?.name).toBe("No shelf");
  // A sub-shelf sits near its parent's region.
  expect(distance(layout.regions.get("s-boss")!.center, layout.regions.get("s-combat")!.center)).toBeLessThan(0.45);
});

it("lays out the same graph the same way every time", () => {
  const a = buildBrainLayout(data);
  const b = buildBrainLayout(data);
  expect([...a.positions.entries()]).toEqual([...b.positions.entries()]);
});

it("draws a brain outline with a cerebellum below the back", () => {
  const back = brainShellPoint([0.3, -0.7, -0.62]);
  const under = brainShellPoint([0.3, -0.95, -0.25]);
  expect(Math.hypot(...back)).toBeGreaterThan(Math.hypot(...under));
});

it("puts a core region in the middle of the brain", () => {
  const layout = buildBrainLayout({ ...data, shelves: [...data.shelves, { id: "g", name: "Global rules", parent_id: null, core: true }], nodes: [...data.nodes, node("g0", ["g"])] });
  expect(brainDepth(layout.regions.get("g")!.center)).toBeLessThan(0.2);
});
