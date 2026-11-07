import { useQuery } from "@tanstack/react-query";
import { Check, CircleAlert, Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { dictationApi, serverText } from "../../api/dictation";
import { microphoneProblem, openMicrophone, useDictationInput, useMicrophones, type DictationInput } from "../../lib/dictationInput";
import { dictationLanguages, useDictationLanguage } from "../../lib/dictationLanguage";
import { t } from "../../lib/i18n";
import type { Recording } from "../../lib/recorder";
import { Button, HelpTip } from "../ui";

/** The microphone is let go after this long, in case the test is left running. */
const TEST_LIMIT_MS = 30_000;
/** Below this level the microphone sends almost nothing: muted, or the wrong one. */
const HEARD = 0.25;

/** A loudness bar. The mark shows the loudest moment so far, so a short word is not missed. */
function LevelMeter({ level, peak }: { level: number; peak: number }) {
  const value = Math.round(level * 100);
  return (
    <div role="meter" aria-label={t("Microphone level")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value} className="relative h-2.5 w-full max-w-md overflow-hidden rounded-full bg-neutral-soft">
      <div className={`h-full rounded-full transition-[width] duration-75 ${level > 0.85 ? "bg-warning" : "bg-primary"}`} style={{ width: `${value}%` }} />
      {peak > 0 && <div className="absolute inset-y-0 w-0.5 bg-ink-muted" style={{ left: `${Math.min(99, Math.round(peak * 100))}%` }} aria-hidden="true" />}
    </div>
  );
}

/** Test listens to the microphone and shows a bar while sound comes in. Nothing is sent anywhere. */
function useMicrophoneTest(input: DictationInput, onDone: () => void) {
  const [listening, setListening] = useState(false);
  const [level, setLevel] = useState(0);
  const [peak, setPeak] = useState(0);
  const [result, setResult] = useState<"heard" | "silent" | { error: string } | null>(null);
  const recording = useRef<Recording | null>(null);
  const loudest = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function release() {
    if (timer.current) clearTimeout(timer.current);
    recording.current?.cancel();
    recording.current = null;
  }
  useEffect(() => release, []);

  async function start() {
    release();
    setResult(null);
    setLevel(0);
    setPeak(0);
    loudest.current = 0;
    try {
      recording.current = await openMicrophone(() => stop(), (value) => {
        setLevel(value);
        if (value > loudest.current) { loudest.current = value; setPeak(value); }
      }, input);
      setListening(true);
      timer.current = setTimeout(stop, TEST_LIMIT_MS);
    } catch (reason) {
      setListening(false);
      setResult({ error: microphoneProblem(reason) });
    }
  }

  function stop() {
    if (!recording.current) return;
    release();
    setListening(false);
    setLevel(0);
    setResult(loudest.current >= HEARD ? "heard" : "silent");
    onDone();
  }

  // Another microphone or clean-up setting takes effect at once while the test runs.
  const settings = JSON.stringify(input);
  const previous = useRef(settings);
  useEffect(() => {
    if (previous.current === settings) return;
    previous.current = settings;
    if (recording.current) void start();
  });

  return { listening, level, peak, result, start, stop };
}

function Switch({ checked, onChange, label, help }: { checked: boolean; onChange: (value: boolean) => void; label: string; help: string }) {
  return (
    <label className="flex items-start gap-3 text-sm">
      <input type="checkbox" className="mt-0.5 h-4 w-4 accent-primary" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span><span className="block font-medium text-ink">{label}</span><span className="block text-xs leading-5 text-ink-muted">{help}</span></span>
    </label>
  );
}

/** Settings > Dictation: the language, which microphone and how its sound is cleaned up, and a quick test that it hears you. */
export function DictationSettings() {
  const supported = typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia);
  const status = useQuery({ queryKey: ["dictation-status"], queryFn: ({ signal }) => dictationApi.status(signal), retry: false, enabled: supported });
  const [language, setLanguage] = useDictationLanguage();
  const [input, setInput] = useDictationInput();
  // Device names show once the microphone has been used, so the list is read again after a test.
  const [listed, setListed] = useState(0);
  const devices = useMicrophones(listed);
  const test = useMicrophoneTest(input, () => setListed((n) => n + 1));
  // The chosen microphone, found by its name when the system has given it a new id.
  const match = input.deviceId ? devices.find((d) => d.deviceId === input.deviceId) ?? (input.label ? devices.find((d) => d.label === input.label) : undefined) : undefined;

  return (
    <div className="space-y-5">
      {!supported ? <p className="text-sm text-ink-muted">{t("This window cannot use a microphone, so dictation is off here.")}</p>
        : status.isError ? <p role="alert" className="text-sm text-danger-ink">{status.error.message}</p>
        : status.data && !status.data.available && <p role="alert" className="flex items-start gap-2 rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning-ink"><CircleAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{t("Dictation is off: {reason}", { reason: serverText(status.data.reason ?? "") })}</p>}

      <div>
        <span className="flex items-center gap-2"><label htmlFor="dictation-language" className="field-label" style={{ marginBottom: 0 }}>{t("Dictation language")}</label><HelpTip label={t("Dictation language")}>{t("Click any text field, then press the microphone in the corner or Ctrl+Shift+Space, and speak. Automatic works for any language but takes about a second longer.")}</HelpTip></span>
        <select id="dictation-language" className="field-input mt-2 max-w-xs" value={language} onChange={(event) => setLanguage(event.target.value)}>
          <option value="auto">{t("Automatic")}</option>
          {dictationLanguages.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      <div className="space-y-3">
        <div>
          <label htmlFor="dictation-microphone" className="field-label">{t("Microphone")}</label>
          <div className="flex flex-wrap items-center gap-3">
            <select id="dictation-microphone" className="field-input min-w-0 max-w-md flex-1" value={match?.deviceId ?? ""} disabled={!supported}
              onChange={(event) => { const device = devices.find((d) => d.deviceId === event.target.value); setInput({ deviceId: device?.deviceId ?? "", label: device?.label ?? "" }); }}>
              <option value="">{t("The system's default microphone")}</option>
              {devices.map((device, i) => <option key={device.deviceId} value={device.deviceId}>{device.label || t("Microphone {number}", { number: i + 1 })}</option>)}
            </select>
            <Button onClick={() => void (test.listening ? test.stop() : test.start())} disabled={!supported} aria-pressed={test.listening} aria-label={test.listening ? t("Stop the microphone test") : t("Test the microphone")}>
              {test.listening ? <Square size={13} fill="currentColor" className="text-danger" aria-hidden="true" /> : <Mic size={16} aria-hidden="true" />}
              {test.listening ? t("Stop") : t("Test")}
            </Button>
          </div>
          {input.deviceId && !match && devices.length > 0 && <p className="mt-1 text-xs text-warning-ink">{t("{name} is not connected, so the default microphone is used.", { name: input.label || t("The chosen microphone") })}</p>}
        </div>
        {test.listening && <div className="space-y-1.5"><LevelMeter level={test.level} peak={test.peak} /><p role="status" className="text-xs text-ink-muted">{t("Say something. The bar moves while sound comes in.")}</p></div>}
        {!test.listening && test.result && (typeof test.result === "object"
          ? <p role="alert" className="flex items-start gap-2 text-sm text-danger-ink"><CircleAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{test.result.error}</p>
          : test.result === "heard"
            ? <p role="status" className="flex items-center gap-2 text-sm text-success-ink"><Check size={16} aria-hidden="true" />{t("The microphone works.")}</p>
            : <p role="status" className="flex items-start gap-2 text-sm text-warning-ink"><CircleAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{t("Almost no sound came in. Choose another microphone, or check that it is not muted in your system settings.")}</p>)}
      </div>

      <fieldset className="space-y-3">
        <legend className="field-label">{t("Sound clean-up")}</legend>
        <Switch checked={input.noiseSuppression} onChange={(value) => setInput({ noiseSuppression: value })} label={t("Reduce background noise")} help={t("Filters out fans, typing and street noise. Turn it off if words get cut off.")} />
        <Switch checked={input.echoCancellation} onChange={(value) => setInput({ echoCancellation: value })} label={t("Remove echo from speakers")} help={t("Keeps sound from your speakers out of the recording. Not needed with headphones.")} />
        <Switch checked={input.autoGainControl} onChange={(value) => setInput({ autoGainControl: value })} label={t("Adjust the volume automatically")} help={t("Makes a quiet or distant voice louder. Turn it off if the level jumps around.")} />
      </fieldset>
    </div>
  );
}
