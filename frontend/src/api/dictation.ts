import { msg, t } from "../lib/i18n";
import { ApiError, request } from "./client";

/** What the speech engine did lately: times only, never the words. */
export interface EngineReport {
  loaded: boolean;
  load_seconds: number | null;
  last_seconds: number | null;
  last_audio_seconds: number | null;
  last_finished: string | null;
  last_error: string | null;
  last_error_at: string | null;
  /** Set while a recording is being turned into text. */
  busy_since: string | null;
  threads: number;
}

/** Whether this build can dictate. The model ships inside the app, so a source checkout may lack it. */
export interface DictationStatus { available: boolean; reason: string | null; engine?: EngineReport }


/** The local service's own sentences about dictation, so they can be shown in the app's language. */
const SERVER_TEXTS = [
  msg("The speech model is not part of this build."),
  msg("The speech engine is not part of this build."),
  msg("The speech engine is still busy with an earlier recording. Wait a moment, or restart Project Moah if this keeps happening."),
  msg("The recording could not be read."),
  msg("The recording is empty."),
];
/** A message from the local service, translated when it is one of the fixed ones. */
export const serverText = (text: string) => (SERVER_TEXTS.includes(text) ? t(text) : text);

/** Live words are previews: one that takes this long is dropped, and the next one tries again. */
export const LIVE_TIMEOUT_MS = 20_000;
/** The final text may take longer on a slow computer: this long, plus two seconds per second of speech. */
export const FINAL_TIMEOUT_MS = 45_000;

/** How long a WAV clip from the recorder lasts: 16 kHz, 16-bit mono after a 44-byte header. */
export const wavSeconds = (wav: Blob) => Math.max(0, wav.size - 44) / 32_000;

/** One signal that aborts when the caller's does or when the time runs out, telling the two apart. */
function deadline(ms: number, outer?: AbortSignal): { signal: AbortSignal; timedOut: () => boolean; done: () => void } {
  const controller = new AbortController();
  let expired = false;
  const timer = setTimeout(() => { expired = true; controller.abort(); }, ms);
  const forward = () => controller.abort();
  if (outer?.aborted) controller.abort();
  outer?.addEventListener("abort", forward);
  return { signal: controller.signal, timedOut: () => expired, done: () => { clearTimeout(timer); outer?.removeEventListener("abort", forward); } };
}

export const dictationApi = {
  status: (signal?: AbortSignal) => request<DictationStatus>("/dictation/status", { signal }),
  /**
   * Sends the recording to the local service, which turns it into text on this computer.
   * live=true is the quicker, slightly less exact pass for words shown while someone speaks. The reply names the language heard.
   * A reply that never comes ends with a clear error instead of leaving "Finishing the text…" on screen.
   */
  async transcribe(wav: Blob, language = "auto", live = false, signal?: AbortSignal) {
    const limit = deadline(live ? LIVE_TIMEOUT_MS : FINAL_TIMEOUT_MS + 2_000 * wavSeconds(wav), signal);
    try {
      return await request<{ text: string; language: string }>(`/dictation/transcribe?language=${encodeURIComponent(language)}${live ? "&live=true" : ""}`, { method: "POST", body: wav, headers: { "Content-Type": "audio/wav" }, signal: limit.signal });
    } catch (error) {
      if (limit.timedOut()) throw new ApiError(t("The speech engine took too long to answer. Try again, or restart Project Moah if this keeps happening."), 0);
      throw error;
    } finally {
      limit.done();
    }
  },
};
