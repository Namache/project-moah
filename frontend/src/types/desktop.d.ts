/** Settings > Accessibility as the desktop app keeps it. auto is the interface size Automatic picks for the window's screen. */
interface DesktopDisplay { zoom: number | "auto"; text: number; auto: number; zoomInUse: number }

interface Window {
  projectBrainDesktop?: Readonly<{ apiToken: string; install?: "flatpak" | "deb" | "linux" | "windows" | "mac"; chooseFolder?: (title?: string) => Promise<string | null>; openAgent?: (url: string) => Promise<boolean>; display?: DesktopDisplay | null; setDisplay?: (prefs: { zoom: number | "auto"; text: number }) => Promise<DesktopDisplay | null>; onDisplayChange?: (listener: (state: DesktopDisplay) => void) => () => void; pomodoro?: import("../api/pomodoro").PomodoroBridge }>;
}
