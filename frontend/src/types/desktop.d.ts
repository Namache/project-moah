interface Window {
  projectBrainDesktop?: Readonly<{ apiToken: string; chooseFolder?: (title?: string) => Promise<string | null>; openAgent?: (url: string) => Promise<boolean> }>;
}
