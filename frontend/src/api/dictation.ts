import { request } from "./client";

/** Whether this build can dictate. The model ships inside the app, so a source checkout may lack it. */
export interface DictationStatus { available: boolean; reason: string | null }

export const dictationApi = {
  status: (signal?: AbortSignal) => request<DictationStatus>("/dictation/status", { signal }),
  /** Sends the recording to the local service, which turns it into text on this computer. */
  transcribe: (wav: Blob, language = "auto", signal?: AbortSignal) =>
    request<{ text: string }>(`/dictation/transcribe?language=${encodeURIComponent(language)}`, { method: "POST", body: wav, headers: { "Content-Type": "audio/wav" }, signal }),
};
