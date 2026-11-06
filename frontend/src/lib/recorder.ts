/**
 * Records the microphone as 16 kHz mono 16-bit WAV, the format the local speech engine reads.
 * The sound stays in this window until it is sent to Project Moah's own local service.
 */
export const TARGET_RATE = 16_000;
/** The local service refuses longer clips; stop a little before that. */
export const MAX_SECONDS = 295;

export interface Recording { stop: () => Promise<Blob>; cancel: () => void }

export async function startRecording(onLimit?: () => void): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
  const context = new AudioContext();
  const source = context.createMediaStreamSource(stream);
  // ScriptProcessor needs no separate worklet file, which the app's content policy would have to allow.
  const processor = context.createScriptProcessor(4096, 1, 1);
  const chunks: Float32Array[] = [];
  let length = 0;
  let limited = false;
  processor.onaudioprocess = (event) => {
    if (limited) return;
    const input = event.inputBuffer.getChannelData(0);
    chunks.push(new Float32Array(input));
    length += input.length;
    if (length / context.sampleRate >= MAX_SECONDS) { limited = true; onLimit?.(); }
  };
  source.connect(processor);
  processor.connect(context.destination);

  const release = () => {
    processor.onaudioprocess = null;
    source.disconnect();
    processor.disconnect();
    for (const track of stream.getTracks()) track.stop();
    void context.close();
  };
  return {
    async stop() {
      const rate = context.sampleRate;
      release();
      const samples = new Float32Array(length);
      let offset = 0;
      for (const chunk of chunks) { samples.set(chunk, offset); offset += chunk.length; }
      return encodeWav(downsample(samples, rate, TARGET_RATE), TARGET_RATE);
    },
    cancel: release,
  };
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
