import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { LoaderCircle, Mic, Square } from "lucide-react";
import { useDictationAvailable } from "./useDictationAvailable";
import { dictationApi, serverText } from "../../api/dictation";
import { insertDictation } from "../../lib/recorder";
import { microphoneProblem, openMicrophone } from "../../lib/dictationInput";
import { LiveDictation } from "../../lib/liveDictation";
import { readDictationLanguage } from "../../lib/dictationLanguage";
import { fieldName, isDictatable, setFieldValue, type TextField } from "../../lib/dictationTarget";
import { onDictationToggle, publishDictationState } from "../../lib/dictationState";
import { matchesShortcut, shortcutAria, shortcutLabel, useDictationShortcut } from "../../lib/dictationShortcut";
import { t } from "../../lib/i18n";

type Phase = "idle" | "starting" | "recording" | "transcribing";

/** Open modal dialogs make the rest of the page inert, so the microphone moves into the top one. */
function topModal(): HTMLDialogElement | null {
  const open = [...document.querySelectorAll<HTMLDialogElement>("dialog[open]")];
  return open.filter((dialog) => { try { return dialog.matches(":modal"); } catch { return true; } }).at(-1) ?? null;
}

/**
 * One microphone for the whole app. Click the text field you want to write in, then press the
 * microphone (or the shortcut from Settings, Ctrl+T at first; Cmd+T on a Mac). Words appear in that field while you speak and get a final,
 * more accurate pass when you stop. Speech is turned into text on this computer, never online.
 * With inline set, the screen shows its own microphone button and this shows none.
 */
export function DictationDock({ inline = false }: { inline?: boolean }) {
  const available = useDictationAvailable();
  const shortcut = useDictationShortcut();
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState("");
  const [focused, setFocused] = useState<TextField | null>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const live = useRef<LiveDictation | null>(null);
  const target = useRef<{ field: TextField; value: string; start: number; end: number } | null>(null);
  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  // Follow which text field has focus, and which modal dialog (if any) the button must live in.
  useEffect(() => {
    if (!available) return;
    const refresh = () => {
      const active = document.activeElement;
      if (isDictatable(active)) setFocused(active);
      else if (!(active instanceof HTMLElement && active.closest("[data-dictation-dock]"))) setFocused(null);
      setHost(topModal());
    };
    refresh();
    const observer = new MutationObserver(refresh);
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["open"] });
    const later = () => setTimeout(refresh, 0);
    document.addEventListener("focusin", refresh);
    document.addEventListener("focusout", later);
    return () => { observer.disconnect(); document.removeEventListener("focusin", refresh); document.removeEventListener("focusout", later); };
  }, [available]);

  useEffect(() => {
    if (!available) return;
    function onKey(event: KeyboardEvent) {
      // Settings > Dictation is choosing new keys: this press belongs to it.
      if (event.defaultPrevented || !matchesShortcut(event, shortcut)) return;
      event.preventDefault();
      void toggle();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => () => { live.current?.cancel(); release(); }, []);

  // A screen with its own microphone button (inline) starts and stops dictation through here.
  useEffect(() => {
    if (!available) return;
    return onDictationToggle(() => void toggle());
  });
  useEffect(() => { publishDictationState({ phase, message }); }, [phase, message]);

  // A note like "No speech was heard" fades after a few seconds.
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(""), 6000);
    return () => clearTimeout(timer);
  }, [message]);

  function release() {
    const field = target.current?.field;
    if (field) field.readOnly = false;
  }

  function place(words: string) {
    const current = target.current!;
    return insertDictation(current.value, words, Math.min(current.start, current.value.length), Math.min(current.end, current.value.length));
  }

  async function toggle() {
    if (phaseRef.current === "recording") return stop();
    if (phaseRef.current === "idle") return start();
  }

  async function start() {
    const field = document.activeElement;
    if (!isDictatable(field)) { setMessage(t("Click the field you want to write in, then press the microphone.")); return; }
    setMessage("");
    const value = field.value;
    target.current = { field, value, start: field.selectionStart ?? value.length, end: field.selectionEnd ?? value.length };
    setPhase("starting");
    try {
      const recording = await openMicrophone(() => void stop());
      // With Automatic, the language heard first is kept for the rest of this dictation: detecting it again each time is slower.
      let language = readDictationLanguage();
      live.current = new LiveDictation(
        recording,
        async (wav, quick) => {
          const reply = await dictationApi.transcribe(wav, language, quick);
          if (language === "auto" && reply.text && reply.language && reply.language !== "auto") language = reply.language;
          return reply.text;
        },
        (words) => { if (target.current) setFieldValue(target.current.field, place(words).value); },
      );
      // Typing would fight the live words, so the field is read-only while dictating.
      field.readOnly = true;
      setPhase("recording");
    } catch (reason) {
      target.current = null;
      setPhase("idle");
      setMessage(microphoneProblem(reason));
    }
  }

  async function stop() {
    const current = live.current;
    const dictated = target.current;
    if (!current || !dictated) return;
    live.current = null;
    setPhase("transcribing");
    try {
      const text = await current.finish();
      release();
      if (!text) {
        setFieldValue(dictated.field, dictated.value);
        setMessage(t("No speech was heard. Try again a little closer to the microphone."));
        return;
      }
      const result = place(text);
      setFieldValue(dictated.field, result.value);
      dictated.field.focus();
      dictated.field.setSelectionRange(result.cursor, result.cursor);
    } catch (reason) {
      release();
      setMessage(reason instanceof Error ? serverText(reason.message) : t("Please try again."));
    } finally {
      target.current = null;
      setPhase("idle");
    }
  }

  if (!available || inline) return null;
  const into = phase === "idle" ? focused : target.current?.field ?? null;
  const name = into ? fieldName(into) : "";
  const label = phase === "recording" ? (name ? t("Stop dictating into {field}", { field: name }) : t("Stop dictating"))
    : phase === "transcribing" ? t("Finishing the text…")
    : name ? t("Dictate into {field}", { field: name }) : t("Dictate");
  const status = phase === "recording" ? t("Listening…") : phase === "transcribing" ? t("Finishing the text…") : "";

  const dock = (
    <div data-dictation-dock="" data-keep-clear="" className="fixed bottom-5 right-5 z-50 flex items-center gap-2">
      {(message || status) && <p role={message ? "alert" : "status"} className={`max-w-72 rounded-lg border px-3 py-1.5 text-xs shadow-card ${message ? "border-danger bg-surface text-danger-ink" : "border-line bg-surface text-ink-muted"}`}>{message || status}</p>}
      <button
        type="button"
        // Keep focus in the field: it is where the words go.
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => void toggle()}
        disabled={phase === "starting" || phase === "transcribing"}
        aria-label={label}
        aria-pressed={phase === "recording"}
        aria-keyshortcuts={shortcutAria(shortcut)}
        title={`${label} (${shortcutLabel(shortcut)})`}
        className={`inline-flex h-11 w-11 items-center justify-center rounded-full border shadow-dialog transition-colors disabled:opacity-70 ${phase === "recording" ? "animate-pulse border-danger bg-danger-soft text-danger-ink" : into ? "border-forest bg-primary text-white hover:opacity-90" : "border-line bg-surface text-ink-muted hover:text-ink"}`}
      >
        {phase === "recording" ? <Square size={16} aria-hidden="true" /> : phase === "idle" ? <Mic size={18} aria-hidden="true" /> : <LoaderCircle size={18} aria-hidden="true" className="animate-spin" />}
      </button>
    </div>
  );
  return createPortal(dock, host ?? document.body);
}
