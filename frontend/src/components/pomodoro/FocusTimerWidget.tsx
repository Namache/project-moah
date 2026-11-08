import { Pause, Play, SkipForward, Square, Timer } from "lucide-react";
import { formatClock, pomodoroBridge, type PomodoroCommand, type PomodoroTimer } from "../../api/pomodoro";
import { applyPomodoroState, usePomodoro, useRemaining } from "../../hooks/usePomodoro";
import { t } from "../../lib/i18n";
import { Button, IconButton, Widget } from "../ui";

const SIZE = 156;
const RADIUS = 68;
const STROKE = 9;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function phaseLabel(timer: PomodoroTimer): string {
  if (timer.phase === "idle") return t("Ready");
  if (timer.waiting) return timer.phase === "break" ? t("Break is ready") : t("Time to focus");
  if (!timer.running) return t("Paused");
  return timer.phase === "break" ? t("Break") : t("Focus");
}

/** The ring empties as the time runs out: green while you focus, blue during a break. */
export function TimerRing({ timer, left }: { timer: PomodoroTimer; left: number }) {
  const share = timer.phase === "idle" || timer.totalMs <= 0 ? 1 : Math.min(1, left / timer.totalMs);
  const colour = timer.phase === "break" ? "var(--color-info)" : "var(--color-forest)";
  const label = phaseLabel(timer);
  return (
    <div className="relative" style={{ width: SIZE, height: SIZE }}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="absolute inset-0 h-full w-full" aria-hidden="true">
        <circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none" stroke="var(--color-line)" strokeWidth={STROKE} />
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke={colour}
          strokeWidth={STROKE}
          strokeLinecap="round"
          strokeDasharray={`${CIRCUMFERENCE * share} ${CIRCUMFERENCE}`}
          transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
          opacity={timer.phase !== "idle" && !timer.running && !timer.waiting ? 0.55 : 1}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        <span className={`text-xs font-semibold uppercase tracking-wider ${timer.phase === "idle" || (!timer.running && !timer.waiting) ? "text-ink-subtle" : timer.phase === "break" ? "text-info-ink" : "text-forest"}`}>{label}</span>
        <span role="timer" className="mt-0.5 text-4xl font-semibold tabular-nums tracking-tight text-ink">{formatClock(left)}</span>
      </div>
    </div>
  );
}

/** The focus timer on Home. It shows only while the timer is turned on in Settings, and only in the desktop app. */
export function FocusTimerWidget() {
  const state = usePomodoro();
  const left = useRemaining(state?.timer);
  if (!state?.settings.enabled) return null;
  const { timer } = state;
  const idle = timer.phase === "idle";
  const run = (name: PomodoroCommand) => {
    void pomodoroBridge()?.command(name).then(applyPomodoroState).catch(() => {});
  };
  const skipLabel = timer.phase === "break" ? t("Skip to focus") : t("Skip to break");
  let startLabel = t("Resume");
  if (idle) startLabel = t("Start");
  else if (timer.waiting) startLabel = timer.phase === "break" ? t("Start break") : t("Start focus");

  return (
    <Widget title={t("Focus timer")} icon={Timer} to="/settings" linkLabel={t("Timer settings")}>
      <div className="flex flex-col items-center gap-3.5 pt-0.5">
        <TimerRing timer={timer} left={left} />
        <div className="flex items-center gap-1">
          {timer.running
            ? <Button variant="primary" onClick={() => run("pause")}><Pause size={16} aria-hidden="true" />{t("Pause")}</Button>
            : <Button variant="primary" onClick={() => run("start")}><Play size={16} aria-hidden="true" />{startLabel}</Button>}
          <IconButton label={skipLabel} icon={SkipForward} disabled={idle} onClick={() => run("skip")} />
          <IconButton label={t("Stop the timer")} icon={Square} disabled={idle} onClick={() => run("stop")} />
        </div>
      </div>
    </Widget>
  );
}
