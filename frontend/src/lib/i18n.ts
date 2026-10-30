import { createElement, Fragment, useSyncExternalStore, type ReactNode } from "react";
import { ru } from "../locales/ru";
import { readPref, writePref } from "./prefs";

/**
 * The app's words, in English or Russian. Bundled, never fetched.
 *
 * English text is the key: write t("Save") and add the Russian to locales/ru.ts. A missing
 * Russian entry falls back to English, and src/i18n.test.ts fails until it is added.
 * - Whole sentences with {placeholders}, never glued pieces: t("Delete {name}?", { name }).
 * - Counts go through tp(), because Russian has three plural forms.
 * - Links or bold inside a sentence go through tx() with <tag>…</tag> markers.
 * - Text kept in a constant outside a component is marked with msg() and passed to t() when shown.
 */
export type Language = "en" | "ru";
export type LanguageChoice = "system" | Language;
/** A Russian entry: one text, or the three plural forms [1, 2–4, 5+] (1 задача, 2 задачи, 5 задач). */
export type Translation = string | readonly [string, string, string];
type Vars = Record<string, string | number>;

/** Marks text in a constant for translation; t() translates it where it is shown. */
export const msg = (text: string) => text;

/**
 * Text kept in a constant outside a component, translated on every read, so the constant can be used as before:
 * labels({ todo: msg("To do") }).todo, or labels({ value: "todo", label: msg("To do") }, ["label"]) for chosen fields.
 */
export function labels<const T extends object>(table: T, fields?: (keyof T)[]): T {
  return new Proxy(table, {
    get: (target, key) => {
      const value = Reflect.get(target, key);
      return typeof value === "string" && (!fields || fields.includes(key as keyof T)) ? t(value) : value;
    },
  });
}

export const languageChoices: { value: LanguageChoice; label: string }[] = [
  { value: "system", label: msg("System") },
  { value: "en", label: "English" },
  { value: "ru", label: "Русский" },
];

const KEY = "pb-language";
const listeners = new Set<() => void>();

function systemLanguage(): Language {
  const wanted = typeof navigator === "undefined" ? [] : navigator.languages?.length ? navigator.languages : [navigator.language];
  for (const tag of wanted) {
    const base = tag?.toLowerCase().split("-")[0];
    if (base === "ru" || base === "en") return base;
  }
  return "en";
}

export function readLanguageChoice(): LanguageChoice {
  const saved = readPref(KEY);
  return saved === "en" || saved === "ru" ? saved : "system";
}

const resolve = (choice: LanguageChoice): Language => (choice === "system" ? systemLanguage() : choice);
let current: Language = resolve(readLanguageChoice());

export const currentLanguage = () => current;

/** The locale for dates and numbers: Russian, or the computer's own English variant. */
export function locale(): string {
  if (current === "ru") return "ru-RU";
  const own = typeof navigator === "undefined" ? "" : navigator.language ?? "";
  return own.toLowerCase().startsWith("en") ? own : "en-US";
}

function apply() {
  if (typeof document !== "undefined") document.documentElement.lang = current;
}

export function setLanguage(choice: LanguageChoice) {
  writePref(KEY, choice === "system" ? null : choice);
  current = resolve(choice);
  apply();
  listeners.forEach((notify) => notify());
}

/** Call once before the first render. */
export function initLanguage() {
  current = resolve(readLanguageChoice());
  apply();
}

const subscribe = (notify: () => void) => { listeners.add(notify); return () => { listeners.delete(notify); }; };

/** The chosen language (System, English or Русский) and a setter. */
export function useLanguageChoice(): [LanguageChoice, (choice: LanguageChoice) => void] {
  return [useSyncExternalStore(subscribe, readLanguageChoice), setLanguage];
}

/** The language in use; components that call it re-render when it changes. */
export function useLanguage(): Language {
  return useSyncExternalStore(subscribe, currentLanguage);
}

const formatNumber = (value: number) => new Intl.NumberFormat(locale()).format(value);

function fill(text: string, vars?: Vars): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) => {
    const value = vars[name];
    return value === undefined ? whole : typeof value === "number" ? formatNumber(value) : value;
  });
}

const russianForms = new Intl.PluralRules("ru-RU");
const englishForms = new Intl.PluralRules("en-US");

function russianForm(forms: readonly [string, string, string], count: number): string {
  const kind = russianForms.select(count);
  return kind === "one" ? forms[0] : kind === "many" ? forms[2] : forms[1];
}

function lookup(text: string): Translation | undefined {
  return current === "ru" ? ru[text] : undefined;
}

/** Translates one whole sentence or label. */
export function t(text: string, vars?: Vars): string {
  const entry = lookup(text);
  if (entry === undefined) return fill(text, vars);
  return fill(typeof entry === "string" ? entry : russianForm(entry, Number(vars?.count ?? 0)), vars);
}

/** A sentence with a count: tp(n, "{count} task", "{count} tasks"). The Russian entry is keyed by the plural form. */
export function tp(count: number, one: string, other: string, vars?: Vars): string {
  const all = { count, ...vars };
  const entry = lookup(other);
  if (entry !== undefined) return fill(typeof entry === "string" ? entry : russianForm(entry, count), all);
  return fill(englishForms.select(count) === "one" ? one : other, all);
}

/**
 * A sentence with links or styling inside: tx("Read <help>the guide</help> first.", { help: (text) => <Link …>{text}</Link> }).
 * {name} placeholders may be text, numbers or elements.
 */
export function tx(text: string, parts: Record<string, ReactNode | ((chunk: string) => ReactNode)>): ReactNode[] {
  const entry = lookup(text);
  const source = typeof entry === "string" ? entry : text;
  const out: ReactNode[] = [];
  const pattern = /<(\w+)>([\s\S]*?)<\/\1>|\{(\w+)\}/g;
  let last = 0;
  for (let match = pattern.exec(source); match; match = pattern.exec(source)) {
    if (match.index > last) out.push(source.slice(last, match.index));
    const part = parts[match[1] ?? match[3]];
    const chunk = (match[2] ?? "").replace(/\{(\w+)\}/g, (whole, name: string) => { const value = parts[name]; return typeof value === "number" ? formatNumber(value) : typeof value === "string" ? value : whole; });
    const node = typeof part === "function" ? part(chunk) : typeof part === "number" ? formatNumber(part) : part;
    out.push(createElement(Fragment, { key: out.length }, node === undefined ? match[0] : node));
    last = pattern.lastIndex;
  }
  if (last < source.length) out.push(source.slice(last));
  return out;
}

/** Re-renders the whole app in the new language. */
export function LanguageRoot({ children }: { children: ReactNode }) {
  const language = useLanguage();
  return createElement(Fragment, { key: language }, children);
}
