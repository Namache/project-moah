import { currentLanguage, locale, msg } from "./i18n";
import type { Install } from "./install";
/** `only` lists the installs an article is for (empty: every install). */
export interface HelpArticle { slug: string; title: string; category: string; summary: string; keywords: string[]; related: string[]; only: string[]; body: string }

const english = import.meta.glob("../content/help/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const russian = import.meta.glob("../content/help/ru/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const list = (value: string | undefined) => (value ?? "").split(",").map((s) => s.trim()).filter(Boolean);

export function parseArticle(slug: string, text: string): HelpArticle {
  const raw = text.replace(/\r\n?/g, "\n"); // a Windows checkout may end lines with \r\n
  const match = raw.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  const meta: Record<string, string> = {};
  for (const line of (match?.[1] ?? "").split("\n")) {
    const at = line.indexOf(":");
    if (at > 0) meta[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
  return { slug, title: meta.title ?? slug, category: meta.category ?? msg("Other"), summary: meta.summary ?? "", keywords: list(meta.keywords), related: list(meta.related), only: list(meta.only), body: (match?.[2] ?? raw).trim() };
}

const load = (files: Record<string, string>): Record<string, HelpArticle> =>
  Object.fromEntries(Object.entries(files).map(([path, raw]) => { const slug = path.split("/").pop()!.replace(/\.md$/, ""); return [slug, parseArticle(slug, raw)]; }));

/** Every article in English, and the Russian ones over them; an article not yet translated stays in English. */
export const helpByLanguage = { en: load(english), ru: { ...load(english), ...load(russian) } };
/** The Russian files alone, for the test that keeps them in step with the English ones. */
export const russianArticles = load(russian);

const fits = (article: HelpArticle, install: Install) => !article.only.length || article.only.includes(install);

/**
 * Keeps the parts of a help text meant for this install. A part for some installs only sits
 * between `{{only flatpak deb}}` and `{{end}}` lines, so a Windows user never reads Flatpak steps.
 */
export function forInstall(body: string, install: Install): string {
  const out: string[] = [];
  let keep = true;
  for (const line of body.split("\n")) {
    const only = line.match(/^\{\{only ([a-z ]+)\}\}$/);
    if (only) { keep = only[1].split(" ").includes(install); continue; }
    if (line === "{{end}}") { keep = true; continue; }
    if (keep) out.push(line);
  }
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

/** The help articles for this install, in the app's language. Categories stay English keys; show them with t(). */
export function helpArticles(install: Install): HelpArticle[] {
  return Object.values(helpByLanguage[currentLanguage()]).filter((a) => fits(a, install)).map((a) => ({ ...a, body: forInstall(a.body, install) }))
    .sort((a, b) => a.title.localeCompare(b.title, locale()));
}

export const categoryOrder = [msg("Getting started"), msg("Core features"), msg("Connect agents"), msg("Troubleshooting")];
export function getArticle(slug: string, install: Install): HelpArticle | undefined {
  const article = helpByLanguage[currentLanguage()][slug];
  return article && fits(article, install) ? { ...article, body: forInstall(article.body, install) } : undefined;
}

/** Local, deterministic search. Every word must appear somewhere; title and keywords weigh most. */
export function searchArticles(query: string, pool: HelpArticle[]): HelpArticle[] {
  const terms = query.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  if (!terms.length) return [];
  const scored = pool.map((article) => {
    const title = article.title.toLowerCase(), keys = article.keywords.join(" ").toLowerCase(), summary = article.summary.toLowerCase(), body = article.body.toLowerCase();
    let score = 0;
    for (const term of terms) {
      const here = (title.includes(term) ? 10 : 0) + (keys.includes(term) ? 6 : 0) + (summary.includes(term) ? 3 : 0) + (body.includes(term) ? 1 : 0);
      if (!here) return { article, score: 0 };
      score += here;
    }
    return { article, score };
  });
  return scored.filter((s) => s.score > 0).sort((a, b) => b.score - a.score || a.article.title.localeCompare(b.article.title, locale())).map((s) => s.article);
}
