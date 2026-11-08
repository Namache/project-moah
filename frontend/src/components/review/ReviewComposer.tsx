import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type RefObject } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bot, Check, FileText, LoaderCircle, Mic, Paperclip, RotateCcw, Send, Square, ThumbsUp, X } from "lucide-react";
import { reviewsApi } from "../../api/reviews";
import { agentsApi, type AgentName, type WorkPrompt } from "../../api/agents";
import { useReopenReview, useReviewDecision } from "../../hooks/useReviews";
import { useDictationAvailable } from "../dictation/useDictationAvailable";
import { toggleDictation, useDictationState } from "../../lib/dictationState";
import { queryKeys } from "../../lib/queries";
import { notify } from "../../lib/notify";
import { t } from "../../lib/i18n";
import { MAX_FEEDBACK_BYTES, MAX_FEEDBACK_FILES, MAX_TEXT_BYTES, type ReviewDecisionInput, type ReviewDetail, type ReviewFile } from "../../types/review";
import { Button } from "../ui";
import { useReviewFileUrl } from "./reviewBits";

const NAME: Record<AgentName, string> = { claude: "Claude Code", codex: "Codex" };
// What you typed for each task stays while you look at other reviews.
const drafts = new Map<string, string>();
const TEXT_NAME = /\.(txt|md|markdown|log|json|csv|tsv|diff|patch|ya?ml|toml|xml|html?|css|jsx?|tsx?|py|gd|rs|go|java|c|cpp|h|sh)$/i;

function problemWith(file: File): string | null {
  const image = file.type.startsWith("image/");
  if (!image && !file.type.startsWith("text/") && !TEXT_NAME.test(file.name)) return t("{name} is not an image or a text file.", { name: file.name || t("That file") });
  if (file.size > (image ? MAX_FEEDBACK_BYTES : MAX_TEXT_BYTES)) return image ? t("{name} is larger than 5 MB.", { name: file.name }) : t("{name} is larger than 1 MB.", { name: file.name });
  return null;
}

function Attachment({ projectId, file, onRemove }: { projectId: string; file: ReviewFile; onRemove: () => void }) {
  const image = file.media_type.startsWith("image/");
  const url = useReviewFileUrl(projectId, image ? file.id : null);
  return (
    <li className="group relative flex h-14 items-center gap-2 overflow-hidden rounded-lg border border-line bg-surface pr-7 text-xs text-ink">
      {image ? <span className="h-full w-14 shrink-0 bg-neutral-soft">{url && <img src={url} alt="" className="h-full w-full object-cover" />}</span> : <FileText size={18} className="ml-2.5 shrink-0 text-forest" aria-hidden="true" />}
      <span className={`max-w-40 truncate ${image ? "" : "pr-1"}`}>{file.filename}</span>
      <button type="button" onClick={onRemove} aria-label={t("Remove {name}", { name: file.filename })} className="absolute right-1 top-1 rounded-full p-0.5 text-ink-subtle hover:bg-hover hover:text-danger-ink focus-visible:outline-2 focus-visible:outline-forest"><X size={14} aria-hidden="true" /></button>
    </li>
  );
}

/** After sending a review back (or answering a question): open the agent with your words typed in, ready to send. */
export function SendBackToAgent({ projectId, taskRef, answered = false, compact = false }: { projectId: string; taskRef: string; answered?: boolean; compact?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ prompt: WorkPrompt; opened: boolean; copied: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preferred, setPreferred] = useState<AgentName>("claude");
  useEffect(() => {
    const controller = new AbortController();
    agentsApi.settings(controller.signal).then((s) => setPreferred(s.default_agent === "codex" ? "codex" : "claude")).catch(() => undefined);
    return () => controller.abort();
  }, []);
  const other: AgentName = preferred === "claude" ? "codex" : "claude";

  async function open(agent: AgentName) {
    setBusy(true); setError(null);
    try {
      const prompt = await reviewsApi.fixPrompt(projectId, taskRef, agent);
      let copied = false;
      try { await navigator.clipboard.writeText(prompt.prompt); copied = true; } catch { /* said below instead */ }
      const opener = window.projectBrainDesktop?.openAgent;
      const opened = opener ? await opener(prompt.url) : false;
      setResult({ prompt, opened, copied });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("The prompt could not be prepared."));
    } finally { setBusy(false); }
  }

  return (
    <div className={compact ? "" : `rounded-xl border p-3 ${answered ? "border-info/30 bg-info-soft/60" : "border-danger/30 bg-danger-soft/60"}`}>
      {!compact && (answered
        ? <p className="text-sm text-ink"><strong className="text-info-ink">{t("Answered.")}</strong> {t("The next agent that opens this project sees your answer first. Or hand it over now:")}</p>
        : <p className="text-sm text-ink"><strong className="text-danger-ink">{t("Sent back.")}</strong> {t("The next agent that opens this project sees your comments first. Or hand them over now:")}</p>)}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button variant="primary" size="sm" disabled={busy} onClick={() => void open(preferred)}><Bot size={15} aria-hidden="true" />{busy ? t("Preparing…") : answered ? t("Open in {agent} with my answer", { agent: NAME[preferred] }) : t("Open in {agent} with my comments", { agent: NAME[preferred] })}</Button>
        <button type="button" disabled={busy} onClick={() => void open(other)} className="text-sm font-semibold text-forest hover:underline disabled:opacity-50">{t("or in {agent}", { agent: NAME[other] })}</button>
      </div>
      {result && (
        <p role="status" className="mt-2 text-xs text-ink-muted">
          {result.opened ? t("{agent} opened with the prompt typed in. Read it, then press Enter to start.", { agent: NAME[result.prompt.agent] }) : t("{agent} could not be opened from here.", { agent: NAME[result.prompt.agent] })}
          {result.copied ? ` ${t("The prompt is also on your clipboard.")}` : ""}
          {result.prompt.agent === "claude" && result.opened && result.prompt.folder ? ` ${t("Choose the folder {folder} in Claude before sending.", { folder: result.prompt.folder })}` : ""}
        </p>
      )}
      {error && <p role="alert" className="mt-2 text-xs text-danger-ink">{error}</p>}
    </div>
  );
}

/** A line put into the comment box: quoted from the review, or an answer picked from the agent's suggestions. */
export interface Quoted { text: string; n: number; answer?: boolean }

/** The microphone button for a comment box: the app's one microphone, writing into that box. */
function RecordButton({ field }: { field: RefObject<HTMLTextAreaElement | null> }) {
  const dictation = useDictationState();
  const canDictate = useDictationAvailable();
  if (!canDictate) return null;
  const listening = dictation.phase === "recording";
  const finishing = dictation.phase === "transcribing" || dictation.phase === "starting";
  return (
    <Button size="sm" variant={listening ? "danger" : "secondary"} onMouseDown={(event) => event.preventDefault()} disabled={finishing}
      onClick={() => { field.current?.focus(); toggleDictation(); }} aria-pressed={listening} aria-keyshortcuts="Control+Shift+Space"
      title={`${listening ? t("Stop dictating") : t("Dictate your comment")} (Ctrl+Shift+Space)`}>
      {listening ? <Square size={14} aria-hidden="true" /> : finishing ? <LoaderCircle size={15} className="animate-spin" aria-hidden="true" /> : <Mic size={15} aria-hidden="true" />}
      {listening ? t("Stop") : t("Record")}
    </Button>
  );
}

function DictationNote() {
  const dictation = useDictationState();
  const listening = dictation.phase === "recording";
  return (
    <p role={dictation.message ? "alert" : "status"} className={`min-w-0 flex-1 truncate text-xs ${dictation.message ? "text-danger-ink" : "text-ink-muted"}`}>
      {dictation.message || (listening ? t("Listening…") : dictation.phase === "transcribing" ? t("Finishing the text…") : "")}
    </p>
  );
}

/** A comment box that grows with its text, up to about ten lines. */
function useGrowing(field: RefObject<HTMLTextAreaElement | null>, text: string) {
  useEffect(() => {
    const box = field.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, 240)}px`;
  }, [field, text]);
}

/**
 * The comment box under the review: write or dictate, attach pictures or text files, then accept
 * (the task moves to Done, nothing else happens) or send it back (your comments go to the agent and
 * the task goes back to In progress). Sending back needs a comment or a file, so the agent knows
 * what to fix. For an agent's question, the box takes your answer instead.
 */
export function ReviewComposer({ detail, quote, criteria, onDecided }: { detail: ReviewDetail; quote: Quoted | null; criteria: { id: string; met: boolean }[]; onDecided: (verdict: ReviewDecisionInput["verdict"], result: ReviewDetail) => void }) {
  const key = `${detail.project_id}:${detail.task_id}`;
  const [comment, setComment] = useState(() => drafts.get(key) ?? "");
  const [uploading, setUploading] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const question = detail.current.kind === "question";
  // A wait Moah opened from the agent's note: you can also just let it go on, or take it as done.
  const fromNote = question && !!detail.current.from_note;
  const field = useRef<HTMLTextAreaElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const client = useQueryClient();
  const decide = useReviewDecision(detail.project_id, detail.task_ref);
  const listening = useDictationState().phase === "recording";
  const files = detail.current.feedback;
  const refresh = () => client.invalidateQueries({ queryKey: queryKeys.review(detail.project_id, detail.task_ref) });

  useEffect(() => { setComment(drafts.get(key) ?? ""); setProblem(null); }, [key]);
  useEffect(() => { drafts.set(key, comment); }, [key, comment]);
  useGrowing(field, comment);
  // A line quoted from the review goes at the end, ready for your words; a picked answer as it is.
  useEffect(() => {
    if (!quote) return;
    setComment((current) => quote.answer ? `${current.trim() ? `${current.trimEnd()}\n` : ""}${quote.text}` : `${current.trimEnd()}${current.trim() ? "\n\n" : ""}> ${quote.text}\n`);
    requestAnimationFrame(() => { const box = field.current; if (box) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); } });
  }, [quote]);

  async function attach(list: File[]) {
    if (!list.length) return;
    setProblem(null);
    const problems = list.map(problemWith).filter((p): p is string => Boolean(p));
    const room = MAX_FEEDBACK_FILES - files.length;
    const good = list.filter((file) => !problemWith(file));
    if (good.length > room) problems.push(t("A comment can carry {count} files.", { count: MAX_FEEDBACK_FILES }));
    setUploading((n) => n + 1);
    try {
      for (const file of good.slice(0, Math.max(room, 0))) {
        await reviewsApi.attach(detail.project_id, detail.task_ref, file, file.name || "pasted image.png");
      }
    } catch (cause) {
      problems.push(cause instanceof Error ? cause.message : t("The file could not be attached."));
    } finally {
      setUploading((n) => n - 1);
      await refresh();
    }
    if (problems.length) setProblem(problems.join(" "));
  }

  async function remove(file: ReviewFile) {
    try { await reviewsApi.remove(detail.project_id, file.id); } catch (cause) { setProblem(cause instanceof Error ? cause.message : t("The file could not be removed.")); }
    await refresh();
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const pasted = [...event.clipboardData.files];
    if (!pasted.length) return;
    event.preventDefault();
    void attach(pasted);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    void attach([...event.dataTransfer.files]);
  }

  const said = comment.trim().length > 0 || files.length > 0;
  const busy = decide.isPending || uploading > 0;

  function send(verdict: ReviewDecisionInput["verdict"]) {
    // Sending back or answering needs words: say so where they go, instead of a grey button.
    if (verdict !== "accept" && verdict !== "approve" && !said) {
      setProblem(verdict === "answer" ? t("Write your answer first.") : t("Write what should change first, so the agent knows what to fix."));
      field.current?.focus();
      return;
    }
    setProblem(null);
    const input: ReviewDecisionInput = verdict === "answer" || verdict === "approve" ? { verdict, comment } : { verdict, comment, criteria };
    decide.mutate(input, {
      onSuccess: (result) => {
        drafts.delete(key);
        setComment("");
        notify(verdict === "accept" ? t("Accepted. {task} is in Done.", { task: detail.task_ref })
          : verdict === "approve" ? t("Approved. {task} is back in progress.", { task: detail.task_ref })
          : verdict === "answer" ? t("Answer sent. {task} is back in progress.", { task: detail.task_ref }) : t("Sent back. {task} is in progress again, with your comments.", { task: detail.task_ref }));
        onDecided(verdict, result);
      },
    });
  }

  return (
    <div onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}
      className={`border-t bg-surface px-5 pb-4 pt-3 transition-colors ${dragging ? "border-forest bg-sage-pale" : "border-line"}`}>
      <label htmlFor="review-comment" className="sr-only">{question ? t("Your answer for the agent") : t("Your comment for the agent")}</label>
      <div className={`rounded-xl border bg-canvas shadow-card focus-within:border-forest ${listening ? "border-danger" : "border-line-strong"}`}>
        <textarea
          id="review-comment"
          ref={field}
          rows={2}
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          onPaste={onPaste}
          maxLength={20000}
          placeholder={question ? t("Write your answer, or press the microphone and say it. Drop or paste screenshots here.") : t("Write what should change, or press the microphone and say it. Drop or paste screenshots here.")}
          className="block w-full resize-none rounded-xl bg-transparent px-4 py-3 text-sm leading-6 text-ink outline-none placeholder:text-ink-subtle"
        />
        {(files.length > 0 || uploading > 0) && (
          <ul className="flex flex-wrap gap-2 px-3 pb-3" aria-label={t("Attached files")}>
            {files.map((file) => <Attachment key={file.id} projectId={detail.project_id} file={file} onRemove={() => void remove(file)} />)}
            {uploading > 0 && <li role="status" className="flex h-14 items-center gap-2 rounded-lg border border-dashed border-line-strong px-3 text-xs text-ink-muted"><LoaderCircle size={15} className="animate-spin" aria-hidden="true" />{t("Attaching…")}</li>}
          </ul>
        )}
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <RecordButton field={field} />
        <Button size="sm" onClick={() => input.current?.click()} disabled={files.length >= MAX_FEEDBACK_FILES}><Paperclip size={15} aria-hidden="true" />{t("Attach")}</Button>
        <input ref={input} type="file" multiple hidden accept="image/png,image/jpeg,image/webp,image/gif,text/*,.md,.log,.json,.csv,.diff,.patch,.yaml,.yml" onChange={(event) => { void attach([...(event.target.files ?? [])]); event.target.value = ""; }} />
        <DictationNote />
        {fromNote ? <>
          <Button disabled={busy} onClick={() => send("answer")} title={t("Sends your answer to the agent; the task goes back to In progress")}>
            <Send size={15} aria-hidden="true" />{t("Send answer")}
          </Button>
          <Button disabled={busy} onClick={() => send("accept")} title={t("It was finished work: the task moves to Done. You can still reopen it from Reviewed.")}>
            <Check size={16} aria-hidden="true" />{t("Accept and move to Done")}
          </Button>
          <Button variant="primary" disabled={busy} onClick={() => send("approve")} title={t("The agent goes on as it planned, with your words if you wrote any; the task goes back to In progress")}>
            <ThumbsUp size={15} aria-hidden="true" />{t("Approve and continue")}
          </Button>
        </> : question ? (
          <Button variant="primary" disabled={busy} onClick={() => send("answer")} title={t("Sends your answer to the agent; the task goes back to In progress")}>
            <Send size={15} aria-hidden="true" />{t("Send answer")}
          </Button>
        ) : <>
          <Button variant="danger" disabled={busy} onClick={() => send("reject")} title={t("Your comments go back to the agent, and the task goes back to In progress")}>
            <RotateCcw size={15} aria-hidden="true" />{t("Send back")}
          </Button>
          <Button variant="primary" disabled={busy} onClick={() => send("accept")} title={t("The task moves to Done. You can still reopen it from Reviewed.")}>
            <Check size={16} aria-hidden="true" />{t("Accept and move to Done")}
          </Button>
        </>}
      </div>
      {fromNote && <p className="mt-2 text-xs text-ink-muted">{t("The agent waits in its chat too. Answering there is fine: when the agent goes on, this closes by itself.")}</p>}
      {problem && <p role="alert" className="mt-2 text-xs text-danger-ink">{problem}</p>}
      {decide.error && <p role="alert" className="mt-2 text-xs text-danger-ink">{(decide.error as Error).message}</p>}
    </div>
  );
}

/**
 * Under accepted work: take the acceptance back. Your comment says what is wrong; the task goes
 * back to In progress and the next agent reads the comment first, as with any send-back.
 */
export function ReopenBox({ detail }: { detail: ReviewDetail }) {
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const reopen = useReopenReview(detail.project_id, detail.task_ref);
  const listening = useDictationState().phase === "recording";
  useGrowing(field, comment);
  useEffect(() => { if (open) requestAnimationFrame(() => field.current?.focus()); }, [open]);

  function send() {
    if (!comment.trim()) { setProblem(t("Write what is wrong first, so the agent knows what to fix.")); field.current?.focus(); return; }
    setProblem(null);
    reopen.mutate(comment, { onSuccess: () => notify(t("Reopened. {task} is in progress again, with your comment.", { task: detail.task_ref })) });
  }

  if (!open) {
    return (
      <div className="flex justify-end border-t border-line bg-surface px-5 py-3">
        <Button variant="secondary" onClick={() => setOpen(true)} title={t("The task goes back to In progress, and the next agent reads your comment first.")}><RotateCcw size={15} aria-hidden="true" />{t("Reopen with a comment")}</Button>
      </div>
    );
  }
  return (
    <div className="border-t border-line bg-surface px-5 pb-4 pt-3">
      <label htmlFor="reopen-comment" className="mb-1.5 block text-sm font-semibold text-ink">{t("What is wrong with {task}?", { task: detail.task_ref })}</label>
      <div className={`rounded-xl border bg-canvas shadow-card focus-within:border-forest ${listening ? "border-danger" : "border-line-strong"}`}>
        <textarea id="reopen-comment" ref={field} rows={2} value={comment} maxLength={20000} onChange={(event) => setComment(event.target.value)}
          placeholder={t("Say what still needs fixing, or press the microphone and say it.")}
          className="block w-full resize-none rounded-xl bg-transparent px-4 py-3 text-sm leading-6 text-ink outline-none placeholder:text-ink-subtle" />
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <RecordButton field={field} />
        <DictationNote />
        <Button variant="quiet" disabled={reopen.isPending} onClick={() => { setOpen(false); setProblem(null); }}>{t("Cancel")}</Button>
        <Button variant="danger" disabled={reopen.isPending} onClick={send}><RotateCcw size={15} aria-hidden="true" />{reopen.isPending ? t("Reopening…") : t("Reopen and send back")}</Button>
      </div>
      {problem && <p role="alert" className="mt-2 text-xs text-danger-ink">{problem}</p>}
      {reopen.error && <p role="alert" className="mt-2 text-xs text-danger-ink">{(reopen.error as Error).message}</p>}
    </div>
  );
}
