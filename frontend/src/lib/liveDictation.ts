import type { Recording } from "./recorder";

/** Wait for at least this much new sound before asking for fresh live words. */
const STEP_SECONDS = 0.8;
/** A part longer than this is closed at the next pause; it gets one exact pass and then stays as it is. */
const SPLIT_AFTER_SECONDS = 6;
/** ...or closed anyway before it outgrows the speech service's quick live window (about ten seconds). */
const FORCE_SPLIT_SECONDS = 9.5;

export const joinWords = (...parts: string[]) => parts.map((part) => part.trim()).filter(Boolean).join(" ");

/**
 * Turns a recording into text while it runs. Only the newest part is sent each time, with the quick
 * live pass. A part is closed at a pause once it is long enough and gets one exact pass, so updates
 * stay quick however long someone talks. When the recording stops, the open part gets its exact pass
 * and the full text is returned.
 */
export class LiveDictation {
  private settled = "";
  private partStart = 0;
  private lastEnd = 0;
  private running: Promise<void> | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private finished = false;

  constructor(
    private readonly recording: Recording,
    /** live=true asks for the quick pass that live words use; false for the exact one. */
    private readonly transcribe: (wav: Blob, live: boolean) => Promise<string>,
    private readonly onWords: (text: string) => void,
    intervalMs = 300,
  ) {
    this.timer = setInterval(() => void this.tick(), intervalMs);
  }

  /** One update, when enough new sound has come in and no update is already on its way. */
  tick(): Promise<void> {
    if (this.running || this.finished) return this.running ?? Promise.resolve();
    const { rate } = this.recording;
    const end = this.recording.length();
    if (end - this.lastEnd < STEP_SECONDS * rate) return Promise.resolve();
    this.running = this.update(end).finally(() => { this.running = null; });
    return this.running;
  }

  private async update(end: number) {
    const { rate } = this.recording;
    this.lastEnd = end;
    let words: string;
    try {
      const seconds = (end - this.partStart) / rate;
      const split = (seconds >= SPLIT_AFTER_SECONDS && this.recording.quietBefore(end)) || seconds >= FORCE_SPLIT_SECONDS;
      words = await this.transcribe(this.recording.clip(this.partStart, end), !split);
      if (this.finished) return;
      if (split) {
        this.settled = joinWords(this.settled, words);
        this.partStart = end;
        this.onWords(this.settled);
        return;
      }
    } catch {
      return; // Live words are a preview; the final pass reports problems.
    }
    this.onWords(joinWords(this.settled, words));
  }

  /** Stops the microphone, waits for any update on its way, and turns the rest into text. */
  async finish(): Promise<string> {
    if (this.timer) clearInterval(this.timer);
    this.recording.stop();
    await this.running;
    this.finished = true;
    const end = this.recording.length();
    const rest = end > this.partStart ? await this.transcribe(this.recording.clip(this.partStart, end), false) : "";
    return joinWords(this.settled, rest);
  }

  cancel() {
    if (this.timer) clearInterval(this.timer);
    this.finished = true;
    this.recording.cancel();
  }
}
