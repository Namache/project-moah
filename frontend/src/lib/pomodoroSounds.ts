import { pomodoroBridge, type PomodoroSettings, type PomodoroSoundKind } from "../api/pomodoro";

// The timer's sounds, played with Web Audio: the built-in ones ship with the app (public/sounds),
// and a sound the person chose comes from Moah's own folder through the desktop app.

type AudioContextClass = typeof AudioContext;
let context: AudioContext | null = null;
const buffers = new Map<string, Promise<AudioBuffer>>();

function audio(): AudioContext | null {
  if (context) return context;
  const Context: AudioContextClass | undefined = typeof window === "undefined" ? undefined : window.AudioContext;
  if (!Context) return null;
  context = new Context();
  return context;
}

/** The cache key changes when the person picks another file, so the new one is loaded. */
function cacheKey(kind: PomodoroSoundKind, settings: PomodoroSettings): string {
  return `${kind}:${settings.sounds[kind]?.file ?? "built-in"}:${settings.sounds[kind]?.name ?? ""}`;
}

async function load(kind: PomodoroSoundKind, settings: PomodoroSettings, ctx: AudioContext): Promise<AudioBuffer> {
  let bytes: ArrayBuffer;
  const own = settings.sounds[kind] ? await pomodoroBridge()?.sound(kind) : null;
  if (own) {
    bytes = own.buffer.slice(own.byteOffset, own.byteOffset + own.byteLength) as ArrayBuffer;
  } else {
    const response = await fetch(`/sounds/${kind}.ogg`);
    if (!response.ok) throw new Error(`Sound ${kind} is missing`);
    bytes = await response.arrayBuffer();
  }
  return ctx.decodeAudioData(bytes);
}

function buffer(kind: PomodoroSoundKind, settings: PomodoroSettings, ctx: AudioContext): Promise<AudioBuffer> {
  const key = cacheKey(kind, settings);
  let pending = buffers.get(key);
  if (!pending) {
    pending = load(kind, settings, ctx);
    pending.catch(() => buffers.delete(key));
    buffers.set(key, pending);
  }
  return pending;
}

/**
 * Plays one of the timer's sounds at the chosen volume. Resolves to false when it couldn't play, for
 * example because the person's own file isn't a sound the app can read.
 */
export async function playTimerSound(kind: PomodoroSoundKind, settings: PomodoroSettings): Promise<boolean> {
  const ctx = audio();
  if (!ctx) return false;
  try {
    if (ctx.state === "suspended") await ctx.resume();
    const decoded = await buffer(kind, settings, ctx);
    const source = ctx.createBufferSource();
    const gain = ctx.createGain();
    // Loudness follows the ear, not the slider: a square curve feels even from 0 to 100.
    gain.gain.value = (settings.volume / 100) ** 2;
    source.buffer = decoded;
    source.connect(gain).connect(ctx.destination);
    source.start();
    return true;
  } catch {
    return false;
  }
}

/** Whether the person's own sound for `kind` can be read, before it is used. */
export async function canPlay(kind: PomodoroSoundKind, settings: PomodoroSettings): Promise<boolean> {
  const ctx = audio();
  if (!ctx) return true;
  try {
    await buffer(kind, settings, ctx);
    return true;
  } catch {
    return false;
  }
}
