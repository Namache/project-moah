import { currentLanguage, locale, msg } from "./i18n";
export interface HelpArticle { slug: string; title: string; category: string; summary: string; keywords: string[]; related: string[]; body: string }

const english = import.meta.glob("../content/help/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const russian = import.meta.glob("../content/help/ru/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const list = (value: string | undefined) => (value ?? "").split(",").map((s) => s.trim()).filter(Boolean);

export function parseArticle(slug: string, raw: string): HelpArticle {
  const match = raw.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  const meta: Record<string, string> = {};
  for (const line of (match?.[1] ?? "").split("\n")) {
    const at = line.indexOf(":");
    if (at > 0) meta[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
  return { slug, title: meta.title ?? slug, category: meta.category ?? msg("Other"), summary: meta.summary ?? "", keywords: list(meta.keywords), related: list(meta.related), body: (match?.[2] ?? raw).trim() };
}

const load = (files: Record<string, string>): Record<string, HelpArticle> =>
  Object.fromEntries(Object.entries(files).map(([path, raw]) => { const slug = path.split("/").pop()!.replace(/\.md$/, ""); return [slug, parseArticle(slug, raw)]; }));

/** Every article in English, and the Russian ones over them; an article not yet translated stays in English. */
export const helpByLanguage = { en: load(english), ru: { ...load(english), ...load(russian) } };
/** The Russian files alone, for the test that keeps them in step with the English ones. */
export const russianArticles = load(russian);

/** The help articles in the app's language. Categories stay English keys; show them with t(). */
export function helpArticles(): HelpArticle[] {
  return Object.values(helpByLanguage[currentLanguage()]).sort((a, b) => a.title.localeCompare(b.title, locale()));
}

export const categoryOrder = [msg("Getting started"), msg("Core features"), msg("Connect agents"), msg("Troubleshooting")];
export const getArticle = (slug: string): HelpArticle | undefined => helpByLanguage[currentLanguage()][slug];

/** Local, deterministic search. Every word must appear somewhere; title and keywords weigh most. */
export function searchArticles(query: string, pool: HelpArticle[] = helpArticles()): HelpArticle[] {
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
