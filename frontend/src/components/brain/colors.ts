import type { NodeKind } from "../../types/graph";

/** Colour per kind of record. In the scene they are brightened past 1 so they bloom into a glow. */
export const KIND_COLORS: Record<NodeKind, string> = {
  task: "#ffb547",
  memory: "#4cc9ff",
  file: "#a78bfa",
  milestone: "#ff6fae",
  checkpoint: "#5cf2a5",
  shelf: "#ffffff",
};
