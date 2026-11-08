import { useEffect } from "react";
import { pomodoroBridge } from "../../api/pomodoro";
import { usePomodoro } from "../../hooks/usePomodoro";
import { playTimerSound } from "../../lib/pomodoroSounds";

/**
 * Plays Moah's sounds when the main process says a break starts, work starts again, or something
 * new arrives in Review. Moah's window plays them even while it is hidden. The main process
 * decides which sounds apply (the Review sound plays whether the focus timer is on or off).
 */
export function PomodoroCues() {
  const state = usePomodoro();
  const settings = state?.settings;
  useEffect(() => {
    const bridge = pomodoroBridge();
    if (!bridge || !settings) return;
    return bridge.onCue((kind) => {
      if (settings.soundsOn) void playTimerSound(kind, settings);
    });
  }, [settings]);
  return null;
}
