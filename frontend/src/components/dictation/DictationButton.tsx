import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LoaderCircle, Mic, Square } from "lucide-react";
import { dictationApi } from "../../api/dictation";
import { insertDictation, startRecording, type Recording } from "../../lib/recorder";
import { t } from "../../lib/i18n";
import { readDictationLanguage } from "../../lib/dictationLanguage";

type Phase = "idle" | "starting" | "recording" | "transcribing";

export function useDictationAvailable(): boolean {
  const supported = typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia);
  const { data } = useQuery({ queryKey: ["dictation-status"], queryFn: ({ signal }) => dictationApi.status(signal), staleTime: Infinity, retry: false, enabled: supported });
  return supported && Boolean(data?.available);
}

/**
 * A microphone button for a text field. Press to start, press again to stop; the words go where
 * the cursor was. Speech is turned into text by Project Moah's local service, never online.
 */
export function DictationButton({ target, value, onChange, field, disabled = false, className = "" }: {
  /** The text field the words go into, to find where its cursor was. */
  target: () => HTMLTextAreaElement | HTMLInputElement | null;
  value: string;
  onChange: (next: string) => void;
  /** The field's name, for the button's label. */
  field: string;
  disabled?: boolean;
  className?: string;
}) {
  const available = useDictationAvailable();
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const recording = useRef<Recording | null>(null);
  const selection = useRef<[number, number] | null>(null);
  const latest = useRef({ value, onChange });
  latest.current = { value, onChange };
  const alive = useRef(true);

  useEffect(() => () => { alive.current = false; recording.current?.cancel(); }, []);

  if (!available) return null;

  async function start() {
    setError("");
    const field = target();
    selection.current = field && document.activeElement === field && field.selectionStart !== null
      ? [field.selectionStart, field.selectionEnd ?? field.selectionStart]
      : null;
    setPhase("starting");
    try {
      recording.current = await startRecording(() => void stop());
      if (!alive.current) { recording.current.cancel(); return; }
      setPhase("recording");
    } catch (reason) {
      setPhase("idle");
      const name = reason instanceof DOMException ? reason.name : "";
      setError(name === "NotAllowedError" || name === "SecurityError"
        ? t("Microphone access was refused. Allow it in your system settings, then try again.")
        : name === "NotFoundError" ? t("No microphone was found.") : t("The microphone could not be started."));
    }
  }

  async function stop() {
    const current = recording.current;
    if (!current) return;
    recording.current = null;
    setPhase("transcribing");
    try {
      const { text } = await dictationApi.transcribe(await current.stop(), readDictationLanguage());
      if (!alive.current) return;
      if (!text) { setError(t("No speech was heard. Try again a little closer to the microphone.")); return; }
      const { value: now, onChange: change } = latest.current;
      const [start, end] = selection.current ?? [now.length, now.length];
      const result = insertDictation(now, text, Math.min(start, now.length), Math.min(end, now.length));
      change(result.value);
      const field = target();
      if (field) requestAnimationFrame(() => { field.focus(); field.setSelectionRange(result.cursor, result.cursor); });
    } catch (reason) {
      if (alive.current) setError(reason instanceof Error ? reason.message : t("Please try again."));
    } finally {
      if (alive.current) setPhase("idle");
    }
  }

  const label = phase === "recording" ? t("Stop dictating into {field}", { field })
    : phase === "transcribing" ? t("Turning speech into text…")
    : t("Dictate into {field}", { field });
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      {phase === "recording" && <span aria-hidden="true" className="text-xs font-medium text-danger-ink">{t("Listening…")}</span>}
      {error && <span role="alert" className="max-w-64 text-right text-xs text-danger-ink">{error}</span>}
      <button
        type="button"
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => void (phase === "recording" ? stop() : phase === "idle" ? start() : undefined)}
        disabled={disabled || phase === "starting" || phase === "transcribing"}
        aria-label={label}
        aria-pressed={phase === "recording"}
        title={label}
        className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border transition-colors disabled:opacity-60 ${phase === "recording" ? "animate-pulse border-danger bg-danger-soft text-danger-ink" : "border-line bg-surface text-ink-muted hover:bg-neutral-soft hover:text-ink"}`}
      >
        {phase === "recording" ? <Square size={13} aria-hidden="true" /> : phase === "transcribing" || phase === "starting" ? <LoaderCircle size={14} aria-hidden="true" className="animate-spin" /> : <Mic size={14} aria-hidden="true" />}
      </button>
      <span role="status" className="sr-only">{phase === "recording" ? t("Listening…") : phase === "transcribing" ? t("Turning speech into text…") : ""}</span>
    </span>
  );
}
