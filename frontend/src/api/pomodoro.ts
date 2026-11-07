// The focus (Pomodoro) timer runs in the desktop app's main process (desktop/pomodoro.cjs), so it
// keeps time while the window is hidden. The page only shows it and sends commands.

export type PomodoroPreset = "25-5" | "40-10" | "50-10" | "52-17" | "90-20" | "custom";
export type PomodoroSoundKind = "break" | "work" | "review";
export type PomodoroCommand = "start" | "pause" | "skip" | "stop";
export type PomodoroMiniSize = "small" | "medium" | "large";

export interface PomodoroSound { file: string; name: string }

export interface PomodoroSettings {
  enabled: boolean;
  preset: PomodoroPreset;
  customWork: number;
  customBreak: number;
  soundsOn: boolean;
  /** 0 to 100. */
  volume: number;
  /** How big the desktop timer is. */
  miniSize: PomodoroMiniSize;
  /** Where the corner timer was dragged to, or null for the bottom-left corner. Changed only by dragging it. */
  miniPosition?: { x: number; y: number } | null;
  /** A sound the person chose instead of the built-in one, or null. */
  sounds: Record<PomodoroSoundKind, PomodoroSound | null>;
}

export interface PomodoroTimer {
  phase: "idle" | "focus" | "break";
  running: boolean;
  /** A part just ended and the next one is set up, waiting for Start. */
  waiting?: boolean;
  /** When the current phase ends (milliseconds since 1970), while running. */
  endsAt: number | null;
  remainingMs: number;
  totalMs: number;
}

export interface PomodoroState {
  settings: PomodoroSettings;
  timer: PomodoroTimer;
  /** How many items wait in Review. */
  review: number;
  /** False on a Linux Wayland session, where the corner timer can't be placed or kept on top. */
  miniSupported: boolean;
  /** The timer is on, but Moah has to start again (through XWayland) before the corner timer can show. */
  restartNeeded: boolean;
  now: number;
}

export type ChooseSoundError = "type" | "size" | "read";

export interface PomodoroBridge {
  get(): Promise<PomodoroState>;
  update(partial: Partial<Omit<PomodoroSettings, "sounds">>): Promise<PomodoroState>;
  command(name: PomodoroCommand): Promise<PomodoroState>;
  chooseSound(kind: PomodoroSoundKind, text: { title: string; filter: string }): Promise<{ state: PomodoroState; error?: ChooseSoundError }>;
  resetSound(kind: PomodoroSoundKind): Promise<PomodoroState>;
  /** The bytes of the person's own sound, or null for the built-in one. */
  sound(kind: PomodoroSoundKind): Promise<Uint8Array | null>;
  quit(): Promise<void>;
  onState(listener: (state: PomodoroState) => void): () => void;
  onCue(listener: (kind: PomodoroSoundKind) => void): () => void;
}

/** The timer exists only in the desktop app; in a plain browser there is none. */
export function pomodoroBridge(): PomodoroBridge | null {
  return (typeof window === "undefined" ? undefined : window.projectBrainDesktop?.pomodoro) ?? null;
}

export const POMODORO_PRESETS: { value: Exclude<PomodoroPreset, "custom">; work: number; rest: number }[] = [
  { value: "25-5", work: 25, rest: 5 },
  { value: "40-10", work: 40, rest: 10 },
  { value: "50-10", work: 50, rest: 10 },
  { value: "52-17", work: 52, rest: 17 },
  { value: "90-20", work: 90, rest: 20 },
];

/** Time left in the current phase, as the page's own clock sees it. */
export function remainingMs(timer: PomodoroTimer, now = Date.now()): number {
  return timer.running && timer.endsAt !== null ? Math.max(0, timer.endsAt - now) : timer.remainingMs;
}

/** "24:13". Hours never show: the longest phase is three hours, written as minutes. */
export function formatClock(ms: number): string {
  const seconds = Math.max(0, Math.ceil(ms / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
