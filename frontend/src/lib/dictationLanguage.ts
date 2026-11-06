import { useState } from "react";
import { readPref, writePref } from "./prefs";

/** The language dictation listens for. "auto" detects it on each clip, which takes about a second longer. */
const KEY = "moah.dictationLanguage";

/** The most spoken languages, in their own names. The speech model understands about 99; these cover most people. */
export const dictationLanguages: { value: string; label: string }[] = [
  { value: "en", label: "English" },
  { value: "zh", label: "中文" },
  { value: "es", label: "Español" },
  { value: "hi", label: "हिन्दी" },
  { value: "ar", label: "العربية" },
  { value: "fr", label: "Français" },
  { value: "pt", label: "Português" },
  { value: "ru", label: "Русский" },
  { value: "de", label: "Deutsch" },
  { value: "ja", label: "日本語" },
  { value: "ko", label: "한국어" },
  { value: "tr", label: "Türkçe" },
  { value: "it", label: "Italiano" },
  { value: "pl", label: "Polski" },
  { value: "uk", label: "Українська" },
  { value: "he", label: "עברית" },
];

export function readDictationLanguage(): string {
  const saved = readPref(KEY);
  return saved && dictationLanguages.some((language) => language.value === saved) ? saved : "auto";
}

export function useDictationLanguage(): [string, (language: string) => void] {
  const [language, setLanguage] = useState(readDictationLanguage);
  return [language, (next) => { writePref(KEY, next === "auto" ? null : next); setLanguage(next); }];
}
