import { Check, Copy } from "lucide-react";
import { Fragment, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { getArticle } from "../../lib/help";
import { useInstall } from "../../lib/install";
import { IntegrationSnippet } from "./IntegrationSnippet";
import { useTimeout } from "../../hooks/useTimeout";
import { t } from "../../lib/i18n";

/**
 * A deliberately small Markdown renderer that builds React elements and never injects HTML,
 * so help text can never run script. External links are shown as text, not clickable.
 */
const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|\[\[[a-z0-9-]+\]\]|\[[^\]]+\]\([^)\s]+\))/g;

function Inline({ text }: { text: string }) {
  const install = useInstall();
  return <>{text.split(INLINE).map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i} className="rounded bg-neutral-soft px-1.5 py-0.5 font-mono text-[0.85em]">{part.slice(1, -1)}</code>;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i} className="font-semibold text-ink"><Inline text={part.slice(2, -2)} /></strong>;
    if (part.startsWith("[[")) { const slug = part.slice(2, -2); const target = getArticle(slug, install); return target ? <Link key={i} to={`/help/${slug}`} className="font-medium text-forest underline">{target.title}</Link> : <Fragment key={i}>{slug}</Fragment>; }
    const link = part.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
    if (link) {
      const [, label, url] = link;
      if (url.startsWith("/")) return <Link key={i} to={url} className="font-medium text-forest underline">{label}</Link>;
      return <Fragment key={i}>{label} <span className="break-all text-xs text-ink-subtle">({url})</span></Fragment>;
    }
    return <Fragment key={i}>{part}</Fragment>;
  })}</>;
}

export function CodeBlock({ code, label }: { code: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const later = useTimeout();
  async function copy() {
    try { await navigator.clipboard.writeText(code); setCopied(true); later(() => setCopied(false), 2000); } catch { /* the text stays selectable */ }
  }
  return (
    <div className="my-3 overflow-hidden rounded-xl border border-line bg-neutral-soft">
      <div className="flex items-center justify-between border-b border-line px-3 py-1.5 text-xs text-ink-muted"><span>{label ?? t("Command")}</span><button type="button" onClick={() => void copy()} aria-label={label ? t("Copy: {name}", { name: label }) : t("Copy command")} className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-medium hover:bg-surface focus-visible:outline-2 focus-visible:outline-forest">{copied ? <Check size={13} /> : <Copy size={13} />}{copied ? t("Copied") : t("Copy")}</button></div>
      <pre tabIndex={0} className="max-h-64 overflow-auto p-3 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-forest text-xs leading-6 text-ink"><code>{code}</code></pre>
    </div>
  );
}

export function Markdown({ source }: { source: string }) {
  const lines = source.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0, key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const fence = line.match(/^```(\w*)/);
    if (fence) { const code: string[] = []; i++; while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]); i++; blocks.push(<CodeBlock key={key++} code={code.join("\n")} label={fence[1] || undefined} />); continue; }
    const snippet = line.match(/^\{\{snippet:(claude|codex)\}\}$/);
    if (snippet) { blocks.push(<IntegrationSnippet key={key++} agent={snippet[1] as "claude" | "codex"} />); i++; continue; }
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (heading) { const level = heading[1].length; const cls = level === 1 ? "mt-8 text-2xl" : level === 2 ? "mt-8 text-xl" : "mt-6 text-base"; blocks.push(<h2 key={key++} className={`${cls} font-semibold tracking-tight text-ink`}><Inline text={heading[2]} /></h2>); i++; continue; }
    const bullet = line.match(/^(-|\d+\.)\s+/);
    if (bullet) {
      const ordered = /\d/.test(bullet[1]); const items: string[] = [];
      while (i < lines.length && /^(-|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^(-|\d+\.)\s+/, ""));
      const Tag = ordered ? "ol" : "ul";
      blocks.push(<Tag key={key++} className={`my-3 space-y-1.5 pl-6 text-sm leading-7 text-ink-muted ${ordered ? "list-decimal" : "list-disc"}`}>{items.map((item, n) => <li key={n}><Inline text={item} /></li>)}</Tag>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,3}\s|```|(-|\d+\.)\s|\{\{snippet)/.test(lines[i])) para.push(lines[i++]);
    blocks.push(<p key={key++} className="my-3 text-sm leading-7 text-ink-muted"><Inline text={para.join(" ")} /></p>);
  }
  return <div>{blocks}</div>;
}
