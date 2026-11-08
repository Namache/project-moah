import { ClipboardCheck, Coffee, Play, RotateCcw, Timer, Upload, Volume2, type LucideIcon } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { POMODORO_PRESETS, pomodoroBridge, type PomodoroMiniSize, type PomodoroPreset, type PomodoroSettings, type PomodoroSoundKind } from "../../api/pomodoro";
import { Choice } from "../Choice";
import { useTimeout } from "../../hooks/useTimeout";
import { applyPomodoroState, usePomodoro } from "../../hooks/usePomodoro";
import { msg, t } from "../../lib/i18n";
import { canPlay, playTimerSound } from "../../lib/pomodoroSounds";
import type { Tone } from "../ui";
import { Button, IconButton } from "../ui";

const presetNames: Record<PomodoroPreset, string> = {
  "25-5": msg("Classic"),
  "40-10": msg("Longer"),
  "50-10": msg("Deep work"),
  "52-17": msg("Long rest"),
  "90-20": msg("Long focus"),
  custom: msg("Your own"),
};

const miniSizes: { value: PomodoroMiniSize; label: string }[] = [
  { value: "small", label: msg("Small") },
  { value: "medium", label: msg("Medium") },
  { value: "large", label: msg("Large") },
];

const soundList: { kind: PomodoroSoundKind; name: string; builtIn: string; icon: LucideIcon; tone: Tone }[] = [
  { kind: "break", name: msg("Break starts"), builtIn: msg("Default: soft chime"), icon: Coffee, tone: "info" },
  { kind: "work", name: msg("Back to work"), builtIn: msg("Default: wooden knock"), icon: Timer, tone: "success" },
  { kind: "review", name: msg("New in Review"), builtIn: msg("Default: calm drop"), icon: ClipboardCheck, tone: "special" },
];

const tileTone: Record<Tone, string> = {
  neutral: "bg-neutral-soft text-neutral-ink",
  info: "bg-info-soft text-info-ink",
  success: "bg-success-soft text-success-ink",
  warning: "bg-warning-soft text-warning-ink",
  danger: "bg-danger-soft text-danger-ink",
  special: "bg-special-soft text-special-ink",
};

/** One short message with an OK button, for a sound file Moah can't use. */
function UnsupportedFileDialog({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const textId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal?.();
    return () => { if (dialog?.open) dialog.close(); };
  }, []);
  return (
    <dialog ref={ref} role="alertdialog" onCancel={(event) => { event.preventDefault(); onClose(); }} aria-labelledby={titleId} aria-describedby={textId} className="dialog-panel m-auto w-[calc(100%-2rem)] max-w-sm rounded-xl border border-line bg-surface p-5 text-ink shadow-dialog backdrop:bg-black/40">
      <h2 id={titleId} className="text-base font-semibold tracking-tight">{t("This file isn't supported")}</h2>
      <p id={textId} className="mt-2 text-sm leading-6 text-ink-muted">{t("You can upload an MP3, OGG, WAV or FLAC file up to 5 MB.")}</p>
      <div className="mt-5 flex justify-end">
        <Button variant="primary" onClick={onClose} autoFocus>{t("OK")}</Button>
      </div>
    </dialog>
  );
}

function clampMinutes(value: string, max: number): number | null {
  const number = Math.round(Number(value));
  return Number.isFinite(number) && number >= 1 ? Math.min(max, number) : null;
}

/** Settings > Focus timer. Only in the desktop app, which runs the timer. */
export function FocusTimerSettings() {
  const state = usePomodoro();
  const [custom, setCustom] = useState<{ work: string; rest: string } | null>(null);
  const bridge = pomodoroBridge();
  if (!bridge || !state) return null;
  const s = state.settings;

  const save = (partial: Partial<Omit<PomodoroSettings, "sounds">>) => {
    void bridge.update(partial).then(applyPomodoroState).catch(() => {});
  };

  const saveCustom = (next: { work: string; rest: string }) => {
    const work = clampMinutes(next.work, 180);
    const rest = clampMinutes(next.rest, 60);
    if (work !== null && rest !== null) save({ customWork: work, customBreak: rest });
  };

  const customWork = custom?.work ?? String(s.customWork);
  const customRest = custom?.rest ?? String(s.customBreak);

  return (
    <section aria-labelledby="settings-focus-timer" className="rounded-xl border border-line bg-surface p-5 shadow-card sm:p-6">
      <h2 id="settings-focus-timer" className="text-base font-semibold tracking-tight">{t("Focus timer")}</h2>
      <div className="mt-3 space-y-5">
        <label className="flex items-start gap-3 text-sm text-ink">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-primary" checked={s.enabled} onChange={(event) => save({ enabled: event.target.checked })} />
          <strong>{t("Show the focus timer")}</strong>
        </label>
        {state.restartNeeded && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg bg-info-soft px-3 py-2 text-sm text-info-ink">
            <span className="min-w-0 flex-1">{t("Restart Project Moah to show the small timer in the corner of the screen.")}</span>
            <Button size="sm" onClick={() => void bridge.quit()}>{t("Quit Project Moah")}</Button>
          </div>
        )}

        <fieldset disabled={!s.enabled} className="space-y-5 disabled:opacity-55">
          <div role="radiogroup" aria-labelledby="pomodoro-type">
            <p id="pomodoro-type" className="field-label">{t("Pomodoro type")}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {[...POMODORO_PRESETS.map((p) => ({ value: p.value as PomodoroPreset, title: `${p.work} / ${p.rest}` })), { value: "custom" as PomodoroPreset, title: t("Custom") }].map(({ value, title }) => {
                const checked = s.preset === value;
                return (
                  <label key={value} className={`grid min-w-24 cursor-pointer gap-px rounded-xl border px-3 py-2 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-forest ${checked ? "border-forest bg-sage-pale shadow-[0_0_0_1px_var(--color-forest)]" : "border-line-strong bg-surface hover:bg-hover"}`}>
                    <input type="radio" name="pomodoro-type" value={value} checked={checked} onChange={() => save({ preset: value })} className="sr-only" />
                    <span className="text-base font-semibold tabular-nums text-ink">{title}</span>
                    <span className="text-xs text-ink-subtle">{t(presetNames[value])}</span>
                  </label>
                );
              })}
            </div>
            {s.preset === "custom" && (
              <div className="mt-3 flex flex-wrap gap-3">
                <label className="grid gap-1 text-xs text-ink-muted">{t("Focus, minutes")}
                  <input type="number" min={1} max={180} className="field-input w-24 tabular-nums" value={customWork} onChange={(event) => setCustom({ work: event.target.value, rest: customRest })} onBlur={() => { saveCustom({ work: customWork, rest: customRest }); setCustom(null); }} />
                </label>
                <label className="grid gap-1 text-xs text-ink-muted">{t("Break, minutes")}
                  <input type="number" min={1} max={60} className="field-input w-24 tabular-nums" value={customRest} onChange={(event) => setCustom({ work: customWork, rest: event.target.value })} onBlur={() => { saveCustom({ work: customWork, rest: customRest }); setCustom(null); }} />
                </label>
              </div>
            )}
          </div>

          <Choice name="pomodoro-mini-size" legend={t("Desktop timer size")} value={s.miniSize} onChange={(miniSize) => save({ miniSize })} choices={miniSizes.map((c) => ({ ...c, label: t(c.label) }))} />

        </fieldset>
      </div>
    </section>
  );
}

/** Settings > Sounds: on by default, and separate from the focus timer, so Review can chime with the timer off. */
export function SoundSettings() {
  const state = usePomodoro();
  const [volume, setVolume] = useState<number | null>(null);
  const [unsupported, setUnsupported] = useState(false);
  const later = useTimeout();
  const bridge = pomodoroBridge();
  if (!bridge || !state) return null;
  const s = state.settings;
  const shownVolume = volume ?? s.volume;

  const save = (partial: Partial<Omit<PomodoroSettings, "sounds">>) => {
    void bridge.update(partial).then(applyPomodoroState).catch(() => {});
  };

  const changeVolume = (value: number) => {
    setVolume(value);
    // Saved once the slider rests, not on every step of a drag.
    later(() => { save({ volume: value }); setVolume(null); }, 300);
  };

  async function choose(kind: PomodoroSoundKind) {
    const result = await bridge!.chooseSound(kind, { title: t("Choose a sound"), filter: t("Sounds") }).catch(() => null);
    if (!result) return;
    applyPomodoroState(result.state);
    if (result.error) { setUnsupported(true); return; }
    // The copy is saved; make sure it really plays before keeping it.
    if (result.state.settings.sounds[kind] && !(await canPlay(kind, result.state.settings))) {
      applyPomodoroState(await bridge!.resetSound(kind).catch(() => null));
      setUnsupported(true);
    }
  }

  return (
    <section aria-labelledby="settings-sounds" className="rounded-xl border border-line bg-surface p-5 shadow-card sm:p-6">
      <h2 id="settings-sounds" className="text-base font-semibold tracking-tight">{t("Sounds")}</h2>
      <div className="mt-3 space-y-3">
        <div>
          <label className="flex items-start gap-3 text-sm text-ink">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-primary" checked={s.soundsOn} aria-describedby="settings-sounds-note" onChange={(event) => save({ soundsOn: event.target.checked })} />
            <strong>{t("Play sounds")}</strong>
          </label>
          <p id="settings-sounds-note" className="ml-7 text-sm text-ink-muted">{t("Works whether the focus timer is on or off.")}</p>
        </div>
        <fieldset disabled={!s.soundsOn} className="space-y-3.5 disabled:opacity-55">
          <div>
            <label htmlFor="pomodoro-volume" className="field-label">{t("Volume")}</label>
            <div className="flex items-center gap-3">
              <Volume2 size={16} className="flex-none text-ink-subtle" aria-hidden="true" />
              <input id="pomodoro-volume" type="range" min={0} max={100} step={1} value={shownVolume} onChange={(event) => changeVolume(Number(event.target.value))} className="w-full max-w-xs accent-primary" />
              <output htmlFor="pomodoro-volume" className="min-w-11 text-sm tabular-nums text-ink-muted">{shownVolume}%</output>
            </div>
          </div>
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line">
            {soundList.map(({ kind, name, builtIn, icon: Icon, tone }) => {
              const own = s.sounds[kind];
              return (
                <li key={kind} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                  <span className={`flex h-9 w-9 flex-none items-center justify-center rounded-lg ${tileTone[tone]}`}><Icon size={16} aria-hidden="true" /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold text-ink">{t(name)}</span>
                    <span className="block truncate text-xs text-ink-subtle">{own ? own.name : t(builtIn)}</span>
                    {kind !== "review" && !s.enabled && <span className="block text-xs text-ink-subtle">{t("Plays while the focus timer is on")}</span>}
                  </span>
                  <span className="flex flex-none items-center gap-1">
                    <Button size="sm" onClick={() => void playTimerSound(kind, { ...s, volume: shownVolume })}><Play size={15} aria-hidden="true" />{t("Play")}</Button>
                    <IconButton label={t("Choose your own sound for {name}", { name: t(name) })} icon={Upload} onClick={() => void choose(kind)} />
                    {own && <IconButton label={t("Use the default sound for {name}", { name: t(name) })} icon={RotateCcw} onClick={() => void bridge.resetSound(kind).then(applyPomodoroState).catch(() => {})} />}
                  </span>
                </li>
              );
            })}
          </ul>
        </fieldset>
      </div>
      {unsupported && <UnsupportedFileDialog onClose={() => setUnsupported(false)} />}
    </section>
  );
}
