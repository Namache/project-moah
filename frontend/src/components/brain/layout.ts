import Graph from "graphology";
import type { BrainGraph, BrainShelf } from "../../types/graph";

/**
 * Places every record inside a brain-shaped volume (design sections 77 and 78).
 * Each top-level shelf owns a region, sub-shelves sit inside their parent's region, records on no
 * shelf sit in a central "current project" region, and a small force layout runs locally so
 * linked records grow together. Pure and deterministic: the same graph always lands the same way.
 */

export type Vec3 = [number, number, number];

// Half-widths of the brain volume: left-right, up-down, front-back.
const BRAIN_RADII: Vec3 = [0.95, 0.82, 1.3];
export const UNSHELVED = "";
// The middle of the brain, deep inside: where the global rules (or records on no shelf) live.
const CORE: Vec3 = [0, -0.12, 0.05];

export interface BrainLayout {
  graph: Graph;
  positions: Map<string, Vec3>;
  regions: Map<string, { name: string; center: Vec3; parent: string | null }>;
}

/** Small seeded generator so layouts are repeatable. */
function random(seed: string) {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    h ^= h >>> 16;
    return (h >>> 0) / 4294967296;
  };
}

/** How far a point is from the centre relative to the brain surface: 1 means on it. */
export function brainDepth([x, y, z]: Vec3): number {
  const [rx, ry, rz] = BRAIN_RADII;
  return Math.hypot(x / rx, y / ry, z / rz);
}

function clampInside(p: Vec3, limit = 0.9): Vec3 {
  const depth = brainDepth(p);
  if (depth <= limit) return p;
  const s = limit / depth;
  return [p[0] * s, p[1] * s, p[2] * s];
}

// Region anchors like brain lobes, ordered so a few shelves already spread front, back and down:
// frontal, occipital, temporal, parietal, then the same lobes on the other side.
const LOBES: Vec3[] = [
  [-0.45, 0.3, 0.68], [0.42, 0.1, -0.78], [-0.62, -0.42, 0.18], [0.45, 0.58, -0.1],
  [0.45, 0.3, 0.68], [-0.42, 0.1, -0.78], [0.62, -0.42, 0.18], [-0.45, 0.58, -0.1],
];

/** Where a top-level shelf's region sits: a lobe, or a golden-spiral spot past eight shelves. */
function regionCenter(index: number, count: number): Vec3 {
  const [rx, ry, rz] = BRAIN_RADII;
  if (count <= LOBES.length) {
    const [x, y, z] = LOBES[index];
    return clampInside([x * rx, y * ry, z * rz], 0.72);
  }
  const t = (index + 0.5) / count;
  const y = 0.8 - 1.5 * t;
  const angle = index * 2.399963;
  const ring = Math.sqrt(Math.max(0, 1 - y * y));
  return clampInside([Math.cos(angle) * ring * rx * 0.7, y * ry * 0.65, Math.sin(angle) * ring * rz * 0.7], 0.75);
}

/** How far a region's records spread from its centre: grows with the region, within limits. */
const regionRadius = (count: number) => Math.min(0.48, 0.12 + 0.034 * Math.sqrt(count));

export function buildBrainLayout(data: BrainGraph, iterations = 90): BrainLayout {
  const graph = new Graph({ multi: true, type: "directed" });
  for (const node of data.nodes) graph.mergeNode(node.key, node);
  for (const link of data.links) {
    if (graph.hasNode(link.source) && graph.hasNode(link.target) && link.source !== link.target) graph.addEdge(link.source, link.target, link);
  }

  // Regions: top-level shelves around the volume, sub-shelves near their parent. The shared tree
  // usually starts from a single root (Knowledge > ...), so its lobes go to the first level with
  // several shelves; the shelves above it sit between their branches.
  const regions: BrainLayout["regions"] = new Map();
  const known = new Set(data.shelves.map((s) => s.id));
  const isTop = (s: BrainShelf) => !s.parent_id || !known.has(s.parent_id);
  const children = new Map<string, BrainShelf[]>();
  for (const s of data.shelves) if (!isTop(s)) children.set(s.parent_id!, [...(children.get(s.parent_id!) ?? []), s]);
  const core = data.shelves.filter((s) => isTop(s) && s.core);
  let shared = data.shelves.filter((s) => isTop(s) && !s.core && s.shared);
  const above: BrainShelf[] = [];
  while (shared.length && shared.length < 3) {
    const next = shared.flatMap((s) => children.get(s.id) ?? [s]);
    if (next.length <= shared.length) break;
    above.push(...shared.filter((s) => children.has(s.id)));
    shared = next;
  }
  const tops = [...data.shelves.filter((s) => isTop(s) && !s.core && !s.shared), ...shared].sort((a, b) => a.name.localeCompare(b.name));
  tops.forEach((shelf, i) => regions.set(shelf.id, { name: shelf.name, center: regionCenter(i, tops.length), parent: null }));
  for (const shelf of above.reverse()) {
    const centers = children.get(shelf.id)!.map((s) => regions.get(s.id)!.center);
    const center = [0, 1, 2].map((a) => centers.reduce((sum, c) => sum + c[a], 0) / centers.length) as Vec3;
    regions.set(shelf.id, { name: shelf.name, center, parent: isTop(shelf) ? null : shelf.parent_id });
  }
  for (const shelf of core) regions.set(shelf.id, { name: shelf.name, center: CORE, parent: null });
  let pending = data.shelves.filter((s) => !regions.has(s.id));
  for (let guard = 0; pending.length && guard < 8; guard++) {
    for (const shelf of pending) {
      const parent = shelf.parent_id ? regions.get(shelf.parent_id) : undefined;
      if (!parent) continue;
      const rnd = random(shelf.id);
      const offset: Vec3 = [(rnd() - 0.5) * 0.36, (rnd() - 0.5) * 0.36, (rnd() - 0.5) * 0.36];
      regions.set(shelf.id, { name: shelf.name, center: clampInside([parent.center[0] + offset[0], parent.center[1] + offset[1], parent.center[2] + offset[2]], 0.8), parent: shelf.parent_id });
    }
    pending = pending.filter((s) => !regions.has(s.id));
  }
  if (!regions.has(UNSHELVED)) regions.set(UNSHELVED, { name: "No shelf", center: CORE, parent: null });

  // Start each record at its region (the middle of several when it sits on many), with jitter.
  const keys = graph.nodes();
  const home = new Map<string, Vec3>();
  const pos = new Map<string, Vec3>();
  const groups = new Map<string, string[]>();
  const group = new Map<string, string>();
  for (const key of keys) {
    const shelves = (graph.getNodeAttribute(key, "shelves") as string[]).filter((id) => regions.has(id));
    const centers = (shelves.length ? shelves : [UNSHELVED]).map((id) => regions.get(id)!.center);
    const c: Vec3 = [0, 0, 0];
    for (const p of centers) for (let a = 0; a < 3; a++) c[a] += p[a] / centers.length;
    home.set(key, c);
    const primary = shelves[0] ?? UNSHELVED;
    group.set(key, primary);
    groups.set(primary, [...(groups.get(primary) ?? []), key]);
    const rnd = random(key);
    const spread = 0.12 + Math.min(0.3, 0.02 * Math.sqrt(keys.length));
    pos.set(key, [c[0] + (rnd() - 0.5) * spread, c[1] + (rnd() - 0.5) * spread, c[2] + (rnd() - 0.5) * spread]);
  }

  // Local force layout: repulsion inside a region, springs along links, a pull home.
  const edges = data.links.filter((l) => pos.has(l.source) && pos.has(l.target) && l.source !== l.target);
  const rnd = random("layout");
  for (let step = 0; step < iterations; step++) {
    const cooling = 1 - step / iterations;
    const force = new Map<string, Vec3>(keys.map((k) => [k, [0, 0, 0]]));
    for (const members of groups.values()) {
      const n = members.length;
      const sample = n > 300 ? 30 : n;
      for (let i = 0; i < n; i++) {
        const a = pos.get(members[i])!;
        const fa = force.get(members[i])!;
        for (let s = 0; s < sample; s++) {
          const j = sample === n ? s : Math.floor(rnd() * n);
          if (j === i) continue;
          const b = pos.get(members[j])!;
          const d: Vec3 = [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
          const dist2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2] + 1e-4;
          const push = (0.00012 * (n / sample)) / dist2;
          for (let k = 0; k < 3; k++) fa[k] += d[k] * push;
        }
      }
    }
    for (const link of edges) {
      const a = pos.get(link.source)!;
      const b = pos.get(link.target)!;
      // Links across regions pull gently, so regions stay apart but lean toward each other.
      const across = group.get(link.source) !== group.get(link.target) ? 0.3 : 1;
      const pull = (link.status === "candidate" ? 0.02 : 0.06 + 0.12 * link.strength) * across;
      const fa = force.get(link.source)!;
      const fb = force.get(link.target)!;
      for (let k = 0; k < 3; k++) {
        const d = (b[k] - a[k]) * pull;
        fa[k] += d;
        fb[k] -= d;
      }
    }
    for (const key of keys) {
      const p = pos.get(key)!;
      const h = home.get(key)!;
      const f = force.get(key)!;
      const next: Vec3 = [0, 0, 0];
      for (let k = 0; k < 3; k++) {
        const move = (f[k] + (h[k] - p[k]) * 0.08) * cooling;
        next[k] = p[k] + Math.max(-0.03, Math.min(0.03, move));
      }
      pos.set(key, next);
    }
  }

  // Keep each region compact: rescale its records' spread around home to the region's radius.
  for (const members of groups.values()) {
    const rms = Math.sqrt(members.reduce((sum, key) => {
      const p = pos.get(key)!;
      const h = home.get(key)!;
      return sum + (p[0] - h[0]) ** 2 + (p[1] - h[1]) ** 2 + (p[2] - h[2]) ** 2;
    }, 0) / members.length) || 1;
    const scale = regionRadius(members.length) / rms;
    for (const key of members) {
      const p = pos.get(key)!;
      const h = home.get(key)!;
      pos.set(key, clampInside([h[0] + (p[0] - h[0]) * scale, h[1] + (p[1] - h[1]) * scale, h[2] + (p[2] - h[2]) * scale]));
    }
  }
  return { graph, positions: pos, regions };
}

// Side outline of a brain: radius at angles around the head, from the front (0) over the top (90)
// to the back (180) and under (270). The low bulge at 295 is the temporal lobe, the one at 225
// the cerebellum. WIDTH is the left-right half-width at the same angles.
const PROFILE = [0.95, 0.93, 0.84, 0.74, 0.76, 0.86, 0.95, 0.9, 0.88, 0.5, 0.6, 0.72, 0.62, 0.6, 0.84];
const WIDTH = [0.6, 0.72, 0.8, 0.82, 0.82, 0.8, 0.66, 0.62, 0.56, 0.5, 0.62, 0.86, 0.8, 0.66, 0.62];
const ANGLES = [0, 30, 60, 90, 120, 150, 180, 205, 225, 245, 270, 295, 315, 330, 345];
const SHELL_SCALE = 1.45;

function around(table: number[], degrees: number): number {
  const n = ANGLES.length;
  let i = n - 1;
  while (i > 0 && ANGLES[i] > degrees) i--;
  const next = (i + 1) % n;
  const span = (next === 0 ? 360 : ANGLES[next]) - ANGLES[i];
  const t = (degrees - ANGLES[i]) / span;
  const [p0, p1, p2, p3] = [table[(i - 1 + n) % n], table[i], table[next], table[(next + 1) % n]];
  // Catmull-Rom, so the outline stays smooth through every point.
  return 0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (3 * p1 - p0 - 3 * p2 + p3) * t * t * t);
}

/**
 * A point of the polygonal brain shell for a direction from the centre (x left-right, y up,
 * z front): the side outline above, two hemispheres split along the top, and shallow folds.
 */
export function brainShellPoint(direction: Vec3): Vec3 {
  const len = Math.hypot(...direction) || 1;
  const [x, y, z] = [direction[0] / len, direction[1] / len, direction[2] / len];
  const degrees = ((Math.atan2(y, z) * 180) / Math.PI + 360) % 360;
  let r = around(PROFILE, degrees);
  const w = around(WIDTH, degrees);
  r *= 1 - 0.1 * Math.exp(-(x * x) / 0.004) * Math.max(0, y); // split between hemispheres
  const fold = 1 + 0.03 * Math.sin(11 * x + 1.3) * Math.sin(9 * y + 0.4) * Math.sin(12 * z + 2.2);
  return [x * w * SHELL_SCALE * fold, (y * r * SHELL_SCALE - 0.08) * fold, z * r * SHELL_SCALE * fold];
}
