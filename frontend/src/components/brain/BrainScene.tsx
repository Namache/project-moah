import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import * as THREE from "three";
import { brainShellPoint, type BrainLayout, type Vec3 } from "./layout";
import { KIND_COLORS } from "./colors";
import { useBrainStore } from "./store";
import type { BrainActivation, BrainGraph } from "../../types/graph";

const LINK_COLOR = new THREE.Color("#3fa9ff");
const PATH_COLOR = new THREE.Color("#d8f3ff");
const GUESS_COLOR = new THREE.Color("#b48cff");
const NODE_RADIUS = 0.02;
const MAX_PULSES = 160;

const reducedMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const pathPairs = (paths: string[][]) => {
  const out = new Set<string>();
  for (const path of paths) for (let i = 1; i < path.length; i++) { out.add(`${path[i - 1]}|${path[i]}`); out.add(`${path[i]}|${path[i - 1]}`); }
  return out;
};

interface SceneProps {
  data: BrainGraph;
  layout: BrainLayout;
  activation: BrainActivation | null;
}

export function BrainScene(props: SceneProps) {
  const select = useBrainStore((s) => s.select);
  const drag = useRef({ down: false, x: 0, y: 0, moved: 0, yaw: 1.2, pitch: 0.18, zoom: 3.8 });
  return (
    <Canvas
      dpr={[1, 2]}
      camera={{ position: [0, 0.4, 4.3], fov: 42 }}
      gl={{ antialias: false, powerPreference: "high-performance" }}
      onCreated={({ gl }) => gl.setClearColor("#03060d")}
      onPointerDown={(e) => { drag.current.down = true; drag.current.x = e.clientX; drag.current.y = e.clientY; drag.current.moved = 0; }}
      onPointerUp={() => { drag.current.down = false; }}
      onPointerLeave={() => { drag.current.down = false; }}
      onPointerMove={(e) => {
        const d = drag.current;
        if (!d.down) return;
        d.moved += Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y);
        d.yaw += (e.clientX - d.x) * 0.006;
        d.pitch = Math.max(-1.1, Math.min(1.1, d.pitch + (e.clientY - d.y) * 0.004));
        d.x = e.clientX; d.y = e.clientY;
      }}
      onWheel={(e) => { drag.current.zoom = Math.max(1.6, Math.min(8, drag.current.zoom + e.deltaY * 0.002)); }}
      onPointerMissed={() => { if (drag.current.moved < 6) select(null); }}
    >
      <Rig drag={drag}>
        <BrainShell />
        <Regions {...props} />
        <Links {...props} />
        <Nodes {...props} drag={drag} />
        <Pulses {...props} />
        <Halo layout={props.layout} />
      </Rig>
      <EffectComposer>
        <Bloom intensity={1.7} luminanceThreshold={0.45} luminanceSmoothing={0.3} mipmapBlur />
      </EffectComposer>
    </Canvas>
  );
}

type Drag = React.RefObject<{ down: boolean; moved: number; yaw: number; pitch: number; zoom: number }>;

/** Slow idle rotation plus drag to turn and wheel to zoom. */
function Rig({ drag, children }: { drag: Drag; children: React.ReactNode }) {
  const group = useRef<THREE.Group>(null);
  const { camera } = useThree();
  const still = useMemo(reducedMotion, []);
  useFrame((_, delta) => {
    const d = drag.current;
    if (!d.down && !still) d.yaw += delta * 0.05;
    if (group.current) {
      group.current.rotation.y += (d.yaw - group.current.rotation.y) * 0.12;
      group.current.rotation.x += (d.pitch - group.current.rotation.x) * 0.12;
    }
    camera.position.z += (d.zoom - camera.position.z) * 0.1;
  });
  return <group ref={group}>{children}</group>;
}

/** The faint polygonal brain outline from the reference image. */
function BrainShell() {
  const { wire, points } = useMemo(() => {
    const base = new THREE.IcosahedronGeometry(1, 4);
    const pos = base.getAttribute("position");
    for (let i = 0; i < pos.count; i++) {
      const [x, y, z] = brainShellPoint([pos.getX(i), pos.getY(i), pos.getZ(i)]);
      pos.setXYZ(i, x, y, z);
    }
    return { wire: new THREE.WireframeGeometry(base), points: base };
  }, []);
  useEffect(() => () => { wire.dispose(); points.dispose(); }, [wire, points]);
  return (
    <group>
      <lineSegments geometry={wire}>
        <lineBasicMaterial color="#1d5fa8" transparent opacity={0.13} blending={THREE.AdditiveBlending} depthWrite={false} />
      </lineSegments>
      <points geometry={points}>
        <pointsMaterial color="#6fc6ff" size={0.012} transparent opacity={0.55} blending={THREE.AdditiveBlending} depthWrite={false} />
      </points>
    </group>
  );
}

/** A soft round glow, drawn once on a canvas (no files, no workers). */
function glowTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.35, "rgba(255,255,255,0.35)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
  }
  return new THREE.CanvasTexture(canvas);
}

/** A soft glow inside each shelf region, brighter while the shelf is awake. */
function Regions({ layout, activation }: SceneProps) {
  const focus = useBrainStore((s) => s.focusShelf);
  const texture = useMemo(glowTexture, []);
  useEffect(() => () => texture.dispose(), [texture]);
  const regions = [...layout.regions.entries()];
  return (
    <group>
      {regions.map(([id, region]) => {
        const awake = activation?.shelves[id] ?? 0;
        const glow = id === focus ? 0.5 : awake ? 0.15 + awake * 0.35 : 0.08;
        const size = region.parent ? 0.7 : 1.05;
        return (
          <sprite key={id || "unshelved"} position={region.center} scale={[size, size, 1]}>
            <spriteMaterial map={texture} color={awake || id === focus ? "#8fdcff" : "#2a6fc0"} transparent opacity={glow} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </sprite>
        );
      })}
    </group>
  );
}

/** A breathing halo around the selected record, so it is easy to find again. */
function Halo({ layout }: { layout: BrainLayout }) {
  const selected = useBrainStore((s) => s.selected);
  const sprite = useRef<THREE.Sprite>(null);
  const texture = useMemo(glowTexture, []);
  useEffect(() => () => texture.dispose(), [texture]);
  useFrame(({ clock }) => {
    if (sprite.current) sprite.current.scale.setScalar(0.22 + 0.04 * Math.sin(clock.getElapsedTime() * 3));
  });
  const at = selected ? layout.positions.get(selected) : undefined;
  if (!at) return null;
  return (
    <sprite ref={sprite} position={at}>
      <spriteMaterial map={texture} color="#ffffff" transparent opacity={0.9} blending={THREE.AdditiveBlending} depthWrite={false} depthTest={false} toneMapped={false} />
    </sprite>
  );
}

function useNodeKeys(data: BrainGraph) {
  return useMemo(() => data.nodes.map((n) => n.key), [data]);
}

function Nodes({ data, layout, activation, drag }: SceneProps & { drag: Drag }) {
  const mesh = useRef<THREE.InstancedMesh>(null);
  const keys = useNodeKeys(data);
  const selected = useBrainStore((s) => s.selected);
  const hovered = useBrainStore((s) => s.hovered);
  const focus = useBrainStore((s) => s.focusShelf);
  const { select, hover } = useBrainStore.getState();
  const geometry = useMemo(() => new THREE.IcosahedronGeometry(NODE_RADIUS, 1), []);
  const included = useMemo(() => new Set(activation?.included ?? []), [activation]);
  const neighbours = useMemo(() => new Set(selected && layout.graph.hasNode(selected) ? layout.graph.neighbors(selected) : []), [selected, layout]);

  useLayoutEffect(() => {
    const m = mesh.current;
    if (!m) return;
    const matrix = new THREE.Matrix4();
    const color = new THREE.Color();
    const scale = new THREE.Vector3();
    const quat = new THREE.Quaternion();
    data.nodes.forEach((node, i) => {
      const p = layout.positions.get(node.key) ?? [0, 0, 0];
      let size = 1 + Math.min(node.degree, 12) * 0.06;
      let light = node.kind === "task" ? 1.35 : 1.15;
      if (activation) {
        const score = activation.nodes[node.key];
        light = included.has(node.key) ? 2.4 : score ? 0.55 + score * 1.3 : 0.16;
        if (included.has(node.key)) size *= 1.35;
      }
      if (focus !== null) light *= node.shelves.includes(focus) || (focus === "" && !node.shelves.length) ? 1.8 : 0.3;
      if (neighbours.has(node.key)) light = Math.max(light, 1.5);
      if (node.key === selected) { light = 3.2; size *= 1.8; }
      if (node.key === hovered) { light = Math.max(light, 2.6); size *= 1.3; }
      matrix.compose(new THREE.Vector3(...p), quat, scale.setScalar(size));
      m.setMatrixAt(i, matrix);
      m.setColorAt(i, color.set(KIND_COLORS[node.kind]).multiplyScalar(light));
    });
    m.count = data.nodes.length;
    m.instanceMatrix.needsUpdate = true;
    if (m.instanceColor) m.instanceColor.needsUpdate = true;
    m.computeBoundingSphere();
  }, [data, layout, activation, included, neighbours, selected, hovered, focus]);
  useEffect(() => () => geometry.dispose(), [geometry]);

  const keyOf = (e: ThreeEvent<PointerEvent | MouseEvent>) => (e.instanceId === undefined ? null : keys[e.instanceId] ?? null);
  return (
    <instancedMesh
      key={data.nodes.length}
      ref={mesh}
      args={[geometry, undefined, Math.max(1, data.nodes.length)]}
      onPointerMove={(e) => { e.stopPropagation(); hover(keyOf(e)); }}
      onPointerOut={() => hover(null)}
      onClick={(e) => { e.stopPropagation(); if (drag.current.moved < 6) select(keyOf(e)); }}
    >
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  );
}

function Links({ data, layout, activation }: SceneProps) {
  const selected = useBrainStore((s) => s.selected);
  const showGuesses = useBrainStore((s) => s.showGuesses);
  const geometry = useMemo(() => new THREE.BufferGeometry(), []);
  useLayoutEffect(() => {
    const onPath = pathPairs(activation?.paths ?? []);
    const shown = data.links.filter((l) => (showGuesses || l.status !== "candidate") && layout.positions.has(l.source) && layout.positions.has(l.target));
    const positions = new Float32Array(shown.length * 6);
    const colors = new Float32Array(shown.length * 6);
    const c = new THREE.Color();
    shown.forEach((link, i) => {
      const a = layout.positions.get(link.source)!;
      const b = layout.positions.get(link.target)!;
      positions.set([...a, ...b], i * 6);
      let light = 0.16 + 0.5 * link.strength * (link.status === "weak" ? 0.6 : 1);
      c.copy(LINK_COLOR);
      if (link.status === "candidate") { c.copy(GUESS_COLOR); light = 0.14; }
      if (activation) light *= 0.45;
      if (onPath.has(`${link.source}|${link.target}`)) { c.copy(PATH_COLOR); light = 1.7; }
      if (selected && (link.source === selected || link.target === selected)) light = Math.max(light, 1.2);
      c.multiplyScalar(light);
      colors.set([c.r, c.g, c.b, c.r, c.g, c.b], i * 6);
    });
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geometry.computeBoundingSphere();
  }, [data, layout, activation, selected, showGuesses, geometry]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <lineSegments geometry={geometry}>
      <lineBasicMaterial vertexColors transparent blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
    </lineSegments>
  );
}

/** Sparks travelling along the paths that carried records into the task's context pack. */
function Pulses({ layout, activation }: SceneProps) {
  const mesh = useRef<THREE.InstancedMesh>(null);
  const geometry = useMemo(() => new THREE.SphereGeometry(0.014, 8, 6), []);
  const tracks = useMemo(() => {
    const out: { points: Vec3[]; lengths: number[]; total: number }[] = [];
    for (const path of activation?.paths ?? []) {
      const points = path.map((k) => layout.positions.get(k)).filter((p): p is Vec3 => Boolean(p));
      if (points.length < 2) continue;
      const lengths = [0];
      for (let i = 1; i < points.length; i++) lengths.push(lengths[i - 1] + Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1], points[i][2] - points[i - 1][2]));
      out.push({ points, lengths, total: lengths[lengths.length - 1] || 1 });
    }
    return out.slice(0, MAX_PULSES / 2);
  }, [activation, layout]);
  const still = useMemo(reducedMotion, []);
  const matrix = useMemo(() => new THREE.Matrix4(), []);
  const at = useMemo(() => new THREE.Vector3(), []);

  useFrame(({ clock }) => {
    const m = mesh.current;
    if (!m) return;
    let n = 0;
    const time = still ? 0.35 : clock.getElapsedTime();
    tracks.forEach((track, t) => {
      for (let s = 0; s < 2; s++) {
        const travelled = (((time * 0.45 + s * 0.5 + t * 0.137) % 1) * track.total);
        let i = 1;
        while (i < track.lengths.length - 1 && track.lengths[i] < travelled) i++;
        const span = track.lengths[i] - track.lengths[i - 1] || 1;
        const f = (travelled - track.lengths[i - 1]) / span;
        const a = track.points[i - 1];
        const b = track.points[i];
        at.set(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f);
        m.setMatrixAt(n++, matrix.makeTranslation(at.x, at.y, at.z));
      }
    });
    m.count = n;
    m.instanceMatrix.needsUpdate = true;
  });
  useEffect(() => () => geometry.dispose(), [geometry]);
  if (!tracks.length) return null;
  return (
    <instancedMesh ref={mesh} args={[geometry, undefined, MAX_PULSES]} raycast={() => null}>
      <meshBasicMaterial color={new THREE.Color("#e9fbff").multiplyScalar(4)} toneMapped={false} />
    </instancedMesh>
  );
}
