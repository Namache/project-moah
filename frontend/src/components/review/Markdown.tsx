import { Children, isValidElement, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertTriangle, CircleCheck, Info, Lightbulb, OctagonAlert } from "lucide-react";
import { msg, t } from "../../lib/i18n";

/**
 * An agent's Markdown, drawn in the app's own colours. Raw HTML is never rendered (it shows as
 * text), and GitHub-style boxes ("> [!WARNING]") become coloured callouts, so an agent can make a
 * warning stand out. The app never opens web pages, so a link copies its address instead.
 */
const CALLOUTS = {
  NOTE: { label: msg("Note"), icon: Info, box: "border-info bg-info-soft text-info-ink" },
  TIP: { label: msg("Tip"), icon: Lightbulb, box: "border-success bg-success-soft text-success-ink" },
  IMPORTANT: { label: msg("Important"), icon: CircleCheck, box: "border-special bg-special-soft text-special-ink" },
  WARNING: { label: msg("Warning"), icon: AlertTriangle, box: "border-warning bg-warning-soft text-warning-ink" },
  CAUTION: { label: msg("Caution"), icon: OctagonAlert, box: "border-danger bg-danger-soft text-danger-ink" },
} as const;
type CalloutKind = keyof typeof CALLOUTS;
const MARKER = /^\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*/i;

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textOf(node.props.children);
  return "";
}

/** "[!WARNING]" at the start of a quote's first paragraph: the kind, and the paragraph without it. */
function callout(children: ReactNode): { kind: CalloutKind; rest: ReactNode[] } | null {
  const parts = Children.toArray(children);
  const firstIndex = parts.findIndex((part) => isValidElement(part));
  const first = parts[firstIndex];
  if (!isValidElement<{ children?: ReactNode }>(first)) return null;
  const match = textOf(first.props.children).match(MARKER);
  if (!match) return null;
  const inner = Children.toArray(first.props.children);
  const head = typeof inner[0] === "string" ? inner[0].replace(MARKER, "") : inner[0];
  const paragraph = [head, ...inner.slice(1)].filter((part) => part !== "");
  const rest = [...parts.slice(0, firstIndex), ...(paragraph.length ? [<p key="first">{paragraph}</p>] : []), ...parts.slice(firstIndex + 1)];
  return { kind: match[1].toUpperCase() as CalloutKind, rest };
}

function Link({ href, children }: { href?: string; children?: ReactNode }) {
  const [copied, setCopied] = useState(false);
  if (!href) return <>{children}</>;
  return (
    <a
      href={href}
      title={copied ? t("Address copied") : t("Copy the address: {href}", { href })}
      onClick={(event) => {
        event.preventDefault();
        void navigator.clipboard?.writeText(href).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }, () => undefined);
      }}
      className="font-medium text-forest underline decoration-forest/40 underline-offset-2 hover:decoration-forest"
    >
      {children}
      {copied && <span role="status" className="ml-1 rounded bg-sage-pale px-1 text-xs font-semibold no-underline">{t("Copied")}</span>}
    </a>
  );
}

const components: Components = {
  h1: ({ children }) => <h3 className="mt-6 text-lg font-semibold tracking-tight text-ink first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mt-6 text-base font-semibold tracking-tight text-ink first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mt-5 text-sm font-semibold uppercase tracking-wider text-ink-muted first:mt-0">{children}</h4>,
  h4: ({ children }) => <h5 className="mt-4 text-sm font-semibold text-ink first:mt-0">{children}</h5>,
  p: ({ children }) => <p className="my-3 leading-7 first:mt-0 last:mb-0">{children}</p>,
  a: ({ href, children }) => <Link href={href}>{children}</Link>,
  ul: ({ children, className }) => <ul className={`my-3 space-y-1.5 pl-5 ${className?.includes("contains-task-list") ? "list-none pl-0" : "list-disc marker:text-ink-subtle"}`}>{children}</ul>,
  ol: ({ children }) => <ol className="my-3 list-decimal space-y-1.5 pl-5 marker:font-semibold marker:text-forest">{children}</ol>,
  li: ({ children }) => <li className="leading-7">{children}</li>,
  input: ({ checked, type }) => type === "checkbox"
    ? <span aria-label={checked ? t("Done") : t("Not done")} role="img" className={`mr-2 inline-flex h-4 w-4 translate-y-0.5 items-center justify-center rounded border text-[10px] font-bold ${checked ? "border-success bg-success text-white" : "border-line-strong bg-surface"}`}>{checked ? "✓" : ""}</span>
    : null,
  blockquote: ({ children }) => {
    const found = callout(children);
    if (!found) return <blockquote className="my-4 border-l-4 border-line-strong pl-4 text-ink-muted">{children}</blockquote>;
    const style = CALLOUTS[found.kind];
    const Icon = style.icon;
    return (
      <div role="note" className={`my-4 first:mt-0 last:mb-0 rounded-lg border-l-4 px-4 py-3 ${style.box}`}>
        <p className="mb-1 flex items-center gap-1.5 text-sm font-semibold"><Icon size={15} aria-hidden="true" />{t(style.label)}</p>
        <div className="text-sm [&_p]:my-1">{found.rest}</div>
      </div>
    );
  },
  code: ({ className, children }) => {
    const block = /language-|\n/.test(`${className ?? ""}${textOf(children)}`);
    return block
      ? <code className={`${className ?? ""} block`}>{children}</code>
      : <code className="rounded bg-neutral-soft px-1.5 py-0.5 font-mono text-[0.85em] text-ink">{children}</code>;
  },
  pre: ({ children }) => <pre className="my-4 first:mt-0 last:mb-0 overflow-x-auto rounded-lg border border-line bg-canvas p-4 font-mono text-xs leading-6 text-ink">{children}</pre>,
  table: ({ children }) => <div className="my-4 first:mt-0 last:mb-0 overflow-x-auto rounded-lg border border-line"><table className="w-full border-collapse text-sm">{children}</table></div>,
  thead: ({ children }) => <thead className="bg-neutral-soft text-left text-xs uppercase tracking-wider text-ink-muted">{children}</thead>,
  th: ({ children, style }) => <th style={style} className="px-3 py-2 font-semibold">{children}</th>,
  td: ({ children, style }) => <td style={style} className="border-t border-line px-3 py-2 align-top">{children}</td>,
  hr: () => <hr className="my-6 border-line" />,
  img: ({ alt }) => <span className="text-ink-subtle">[{alt || t("image")}]</span>,
  strong: ({ children }) => <strong className="font-semibold text-ink">{children}</strong>,
  del: ({ children }) => <del className="text-ink-subtle">{children}</del>,
};

export function Markdown({ text, className = "" }: { text: string; className?: string }) {
  return (
    <div className={`text-sm text-ink ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} skipHtml>{text}</ReactMarkdown>
    </div>
  );
}
