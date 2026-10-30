interface Window {
  projectBrainDesktop?: Readonly<{ apiToken: string; install?: "flatpak" | "deb" | "linux" | "windows" | "mac"; chooseFolder?: (title?: string) => Promise<string | null>; openAgent?: (url: string) => Promise<boolean> }>;
}
