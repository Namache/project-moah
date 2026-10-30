interface Window {
  projectBrainDesktop?: Readonly<{ apiToken: string; chooseFolder?: () => Promise<string | null>; openAgent?: (url: string) => Promise<boolean> }>;
}
