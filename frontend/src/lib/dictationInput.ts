import { useEffect, useState } from "react";
import { t } from "./i18n";
import { readPref, writePref } from "./prefs";
import { startRecording, type Recording } from "./recorder";

/**
 * Which microphone dictation listens to, and how the sound is cleaned up before the speech engine
 * hears it. Kept in this window only; the defaults are what dictation always used.
 */
export interface DictationInput {
  /** The chosen microphone, or "" for the system's default. */
  deviceId: string;
  /** Its name, to find it again when the system gives it a new id. */
  label: string;
  noiseSuppression: boolean;
  echoCancellation: boolean;
  autoGainControl: boolean;
}

const KEY = "moah.dictationInput";
export const DEFAULT_INPUT: DictationInput = { deviceId: "", label: "", noiseSuppression: true, echoCancellation: true, autoGainControl: true };

export function readDictationInput(): DictationInput {
  try {
    const saved = JSON.parse(readPref(KEY) ?? "{}") as Partial<DictationInput>;
    const flag = (value: unknown, fallback: boolean) => (typeof value === "boolean" ? value : fallback);
    return {
      deviceId: typeof saved.deviceId === "string" ? saved.deviceId : "",
      label: typeof saved.label === "string" ? saved.label : "",
      noiseSuppression: flag(saved.noiseSuppression, true),
      echoCancellation: flag(saved.echoCancellation, true),
      autoGainControl: flag(saved.autoGainControl, true),
    };
  } catch {
    return DEFAULT_INPUT;
  }
}

export function useDictationInput(): [DictationInput, (change: Partial<DictationInput>) => void] {
  const [input, setInput] = useState(readDictationInput);
  return [input, (change) => {
    const next = { ...input, ...change };
    const isDefault = (Object.keys(DEFAULT_INPUT) as (keyof DictationInput)[]).every((key) => next[key] === DEFAULT_INPUT[key]);
    writePref(KEY, isDefault ? null : JSON.stringify(next));
    setInput(next);
  }];
}

export async function microphones(): Promise<MediaDeviceInfo[]> {
  try {
    const devices = await navigator.mediaDevices?.enumerateDevices?.();
    // "default" and "communications" are the system's own aliases for a real microphone.
    return (devices ?? []).filter((device) => device.kind === "audioinput" && device.deviceId && !["default", "communications"].includes(device.deviceId));
  } catch {
    return [];
  }
}

/** The microphones this computer has, kept current when one is plugged in or out. */
export function useMicrophones(refresh = 0): MediaDeviceInfo[] {
  const [list, setList] = useState<MediaDeviceInfo[]>([]);
  useEffect(() => {
    let live = true;
    const load = () => void microphones().then((found) => { if (live) setList(found); });
    load();
    navigator.mediaDevices?.addEventListener?.("devicechange", load);
    return () => { live = false; navigator.mediaDevices?.removeEventListener?.("devicechange", load); };
  }, [refresh]);
  return list;
}

/**
 * What to ask the browser for. A chosen microphone that is gone (unplugged, or given a new id) is
 * found again by its name, or dictation falls back to the system's default instead of failing.
 */
export async function audioConstraints(input: DictationInput = readDictationInput()): Promise<MediaTrackConstraints> {
  const constraints: MediaTrackConstraints = { channelCount: 1, noiseSuppression: input.noiseSuppression, echoCancellation: input.echoCancellation, autoGainControl: input.autoGainControl };
  if (!input.deviceId) return constraints;
  const found = await microphones();
  const device = found.find((d) => d.deviceId === input.deviceId) ?? (input.label ? found.find((d) => d.label === input.label) : undefined);
  return device ? { ...constraints, deviceId: { exact: device.deviceId } } : constraints;
}

/** Starts recording from the microphone chosen in Settings, or from the default one if that one will not open. */
export async function openMicrophone(onLimit?: () => void, onLevel?: (level: number) => void, input?: DictationInput): Promise<Recording> {
  const constraints = await audioConstraints(input);
  try {
    return await startRecording(onLimit, { constraints, onLevel });
  } catch (error) {
    const gone = error instanceof DOMException && ["OverconstrainedError", "NotFoundError", "NotReadableError"].includes(error.name);
    if (!gone || !constraints.deviceId) throw error;
    const { deviceId: _chosen, ...rest } = constraints;
    return startRecording(onLimit, { constraints: rest, onLevel });
  }
}

/** A sentence for a microphone that would not start, with what to do about it. */
export function microphoneProblem(reason: unknown): string {
  const name = reason instanceof DOMException ? reason.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") return t("Microphone access was refused. Allow it in your system settings, then try again.");
  if (name === "NotFoundError" || name === "OverconstrainedError") return t("No microphone was found.");
  if (name === "NotReadableError") return t("The microphone is in use by another app or blocked by the system. Close the other app, or choose another microphone in Settings > Dictation.");
  return t("The microphone could not be started.");
}
