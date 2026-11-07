/**
 * Records the microphone as 16 kHz mono 16-bit WAV, the format the local speech engine reads.
 * The sound stays in this window until it is sent to Project Moah's own local service.
 */
export const TARGET_RATE = 16_000;
/** The local service refuses longer clips; stop a little before that. */
export const MAX_SECONDS = 295;

/**
 * A running recording. Positions count samples at the microphone's own rate (rate), so parts of the
 * recording can be sent while it goes on: live words come from the newest part, then a final pass.
 */
export interface Recording {
  rate: number;
  /** Samples recorded so far. */
  length: () => number;
  /** The recording between two positions, as WAV for the local speech service. */
  clip: (from: number, to: number) => Blob;
  /** Whether the half second before a position is quiet: a pause, a good place to split. */
  quietBefore: (at: number) => boolean;
  /** Stop the microphone. The recorded sound stays readable through clip(). */
  stop: () => void;
  cancel: () => void;
}

export interface RecordingOptions {
  /** Which microphone, and how its sound is cleaned up: Settings > Dictation. */
  constraints?: MediaTrackConstraints;
  /** How loud the newest sound is, from 0 to 1, a few times a second: for a level meter. */
  onLevel?: (level: number) => void;
}

export async function startRecording(onLimit?: () => void, { constraints, onLevel }: RecordingOptions = {}): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: constraints ?? { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
  const context = new AudioContext();
  // A context made outside a click can start paused, and a paused one records nothing.
  if (context.state === "suspended") await context.resume().catch(() => {});
  const source = context.createMediaStreamSource(stream);
  // ScriptProcessor needs no separate worklet file, which the app's content policy would have to allow.
  const processor = context.createScriptProcessor(4096, 1, 1);
  const rate = context.sampleRate;
  const store = new SampleStore();
  let limited = false;
  processor.onaudioprocess = (event) => {
    if (limited) return;
    const chunk = event.inputBuffer.getChannelData(0);
    store.push(chunk);
    onLevel?.(level(chunk));
    if (store.length / rate >= MAX_SECONDS) { limited = true; onLimit?.(); }
  };
  source.connect(processor);
  processor.connect(context.destination);

  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    processor.onaudioprocess = null;
    source.disconnect();
    processor.disconnect();
    for (const track of stream.getTracks()) track.stop();
    void context.close();
  };
  return {
    rate,
    length: () => store.length,
    clip: (from, to) => encodeWav(downsample(store.slice(from, to), rate, TARGET_RATE), TARGET_RATE),
    quietBefore: (at) => isQuiet(store.slice(Math.max(0, at - Math.round(rate / 2)), at)),
    stop: release,
    cancel: release,
  };
}

/** Recorded sound in one growing buffer, so reading a part of it does not copy every chunk again. */
export class SampleStore {
  private buffer = new Float32Array(16_000 * 30);
  length = 0;
  push(input: Float32Array) {
    if (this.length + input.length > this.buffer.length) {
      const bigger = new Float32Array(Math.max(this.buffer.length * 2, this.length + input.length));
      bigger.set(this.buffer.subarray(0, this.length));
      this.buffer = bigger;
    }
    this.buffer.set(input, this.length);
    this.length += input.length;
  }
  slice(from: number, to: number): Float32Array {
    return this.buffer.slice(Math.max(0, from), Math.min(to, this.length));
  }
}

/** Loudness from 0 to 1 for a level meter: speech at a normal distance reaches about the middle. */
export function level(samples: Float32Array): number {
  if (!samples.length) return 0;
  let sum = 0;
  for (const value of samples) sum += value * value;
  const rms = Math.sqrt(sum / samples.length);
  // Decibels from -60 (silence) to 0 (as loud as it gets), so quiet voices still move the bar.
  return rms <= 0 ? 0 : Math.max(0, Math.min(1, (20 * Math.log10(rms) + 60) / 60));
}

/** Quiet enough to count as a pause between phrases (a little above what the speech service treats as silence). */
export function isQuiet(samples: Float32Array): boolean {
  if (!samples.length) return true;
  let sum = 0;
  for (const value of samples) sum += value * value;
  return Math.sqrt(sum / samples.length) < 0.01;
}

/** Averages each run of input samples into one output sample: a simple low-pass that keeps speech clear. */
export function downsample(samples: Float32Array, from: number, to: number): Float32Array {
  if (from === to) return samples;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(samples.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    out[i] = end > start ? sum / (end - start) : 0;
  }
  return out;
}

export function encodeWav(samples: Float32Array, rate: number): Blob {
  return new Blob([wavBytes(samples, rate)], { type: "audio/wav" });
}

export function wavBytes(samples: Float32Array, rate: number): ArrayBuffer {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const value = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, value < 0 ? value * 0x8000 : value * 0x7fff, true);
  }
  return buffer;
}

/** Puts dictated words where the cursor was, with a space on each side where words would otherwise touch. */
export function insertDictation(value: string, words: string, start = value.length, end = start): { value: string; cursor: number } {
  const before = value.slice(0, start);
  const after = value.slice(end);
  const lead = before && !/\s$/.test(before) ? " " : "";
  const trail = after && !/^\s/.test(after) ? " " : "";
  const inserted = `${lead}${words}${trail}`;
  return { value: before + inserted + after, cursor: before.length + lead.length + words.length };
}
