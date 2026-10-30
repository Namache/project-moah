import { ArrowLeft, BookOpen, ClipboardCheck, Compass, Plug, Search, Wrench } from "lucide-react";
import { useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { Markdown } from "../components/help/Markdown";
import { EmptyState, PageHeading } from "../components/ui";
import { articles, categoryOrder, getArticle, searchArticles, type HelpArticle } from "../lib/help";

const categoryIcons: Record<string, typeof BookOpen> = { "Getting started": Compass, "Core features": BookOpen, "Connect agents": Plug, Troubleshooting: Wrench };

function Card({ article }: { article: HelpArticle }) {
  return (
    <Link to={`/help/${article.slug}`} className="block rounded-xl border border-line bg-surface p-5 shadow-card hover:border-forest/40 focus-visible:outline-2 focus-visible:outline-forest">
      <h3 className="text-base font-semibold text-ink">{article.title}</h3>
      <p className="mt-1 text-sm leading-6 text-ink-muted">{article.summary}</p>
    </Link>
  );
}

export function HelpPage() {
  const [query, setQuery] = useState("");
  const results = searchArticles(query);
  return (
    <div>
      <PageHeading title="How can we help?" />
      <form role="search" aria-label="Help search" className="relative mt-6 max-w-xl" onSubmit={(e) => e.preventDefault()}>
        <Search size={16} className="pointer-events-none absolute left-3.5 top-3.5 text-ink-subtle" aria-hidden="true" />
        <input type="search" aria-label="Search help" className="field-input !pl-10" placeholder="Search help: locked, codex, context, supersede…" value={query} onChange={(e) => setQuery(e.target.value)} />
      </form>
      {query.trim() ? (
        <section className="mt-8" aria-live="polite" aria-label="Search results">
          {results.length === 0 ? <EmptyState icon={<Search size={26} />} title={`No help matches "${query.trim()}"`}>Try a shorter word, such as "task", "memory", "git" or "codex".</EmptyState>
            : <><p className="mb-3 text-sm text-ink-muted">{results.length} {results.length === 1 ? "article" : "articles"}</p><div className="grid gap-4 md:grid-cols-2">{results.map((a) => <Card key={a.slug} article={a} />)}</div></>}
        </section>
      ) : (
        <div className="mt-8 space-y-10">
          {categoryOrder.map((category) => {
            const group = articles.filter((a) => a.category === category);
            const Icon = categoryIcons[category] ?? BookOpen;
            return group.length ? (
              <section key={category} aria-labelledby={`cat-${category}`}>
                <h2 id={`cat-${category}`} className="mb-3 flex items-center gap-2 text-sm font-bold uppercase tracking-[0.14em] text-ink-subtle"><Icon size={16} aria-hidden="true" />{category}</h2>
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{group.map((a) => <Card key={a.slug} article={a} />)}</div>
              </section>
            ) : null;
          })}
          <p className="flex items-center gap-2 text-sm text-ink-muted"><ClipboardCheck size={16} aria-hidden="true" />New here? <Link to="/help/getting-started" className="font-medium text-forest underline">Start with Getting started</Link>, or <Link to="/?tour=1" className="font-medium text-forest underline">take the guided tour</Link>.</p>
        </div>
      )}
    </div>
  );
}

export function HelpArticlePage() {
  const { slug = "" } = useParams();
  const article = getArticle(slug);
  if (!article) return <Navigate to="/help" replace />;
  const related = article.related.map(getArticle).filter((a): a is HelpArticle => Boolean(a));
  return (
    <article className="max-w-3xl">
      <Link to="/help" className="inline-flex items-center gap-1.5 rounded-lg text-sm font-medium text-ink-muted hover:text-forest focus-visible:outline-2 focus-visible:outline-forest"><ArrowLeft size={16} aria-hidden="true" />All help</Link>
      <p className="mt-6 text-xs font-bold uppercase tracking-[0.16em] text-forest">{article.category}</p>
      <h1 className="mt-1 text-3xl font-semibold tracking-tight text-ink">{article.title}</h1>
      <Markdown source={article.body} />
      {related.length > 0 && <aside aria-label="Related articles" className="mt-10 border-t border-line pt-6"><h2 className="text-sm font-semibold text-ink">Related</h2><ul className="mt-2 space-y-1">{related.map((a) => <li key={a.slug}><Link to={`/help/${a.slug}`} className="text-sm font-medium text-forest underline">{a.title}</Link></li>)}</ul></aside>}
    </article>
  );
}
