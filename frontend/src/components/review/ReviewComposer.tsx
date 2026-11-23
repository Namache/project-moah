import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type RefObject } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bot, Check, Copy, FileText, LoaderCircle, Mic, Paperclip, RotateCcw, Send, Square, ThumbsUp, X } from "lucide-react";
import { reviewsApi } from "../../api/reviews";
import type { AgentName, FixPrompt, ReviewChat, WorkPrompt } from "../../api/agents";
import { useReopenReview, useReviewDecision } from "../../hooks/useReviews";
import { useDictationAvailable } from "../dictation/useDictationAvailable";
import { toggleDictation, useDictationState } from "../../lib/dictationState";
import { shortcutAria, shortcutLabel, useDictationShortcut } from "../../lib/dictationShortcut";
import { queryKeys } from "../../lib/queries";
import { notify } from "../../lib/notify";
import { t } from "../../lib/i18n";
import { MAX_FEEDBACK_BYTES, MAX_FEEDBACK_FILES, MAX_TEXT_BYTES, type ReviewDecisionInput, type ReviewDetail, type ReviewFile } from "../../types/review";
import { Button } from "../ui";
import { useReviewFileUrl } from "./reviewBits";
import { TYPING, useSingleKeys } from "../../lib/reviewKeys";

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

// A chat that is waiting takes in the decision within about two seconds; one more look shortly
// after the box shows is enough to say it arrived.
const LOOK_AGAIN_MS = 4000;
const UNKNOWN_CHAT: ReviewChat = { kind: "unknown", agent: null, url: null, delivered: false, resume: null };

/**
 * After sending a review back (or answering a question): go to the chat that asked, where the decision is delivered.
 * A chat Moah cannot open says so; a new chat is only the main button when Moah does not know the chat at all.
 */
export function SendBackToAgent({ projectId, taskRef, answered = false, compact = false }: { projectId: string; taskRef: string; answered?: boolean; compact?: boolean }) {
  const [busy, setBusy] = useState(false);
  // prompt: null prompt means Go to the chat (nothing was typed in anywhere).
  const [result, setResult] = useState<{ prompt: WorkPrompt | null; agent: AgentName; opened: boolean; copied: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asked, setAsked] = useState<{ prompt: FixPrompt | null; failed: boolean }>({ prompt: null, failed: false });
  const [resumeCopied, setResumeCopied] = useState(false);

  // Fetched as the box shows, so the button knows the chat before it is pressed.
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    setAsked({ prompt: null, failed: false }); setResult(null); setError(null);
    const look = (first: boolean) => {
      reviewsApi.fixPrompt(projectId, taskRef).then((prompt) => {
        if (!alive) return;
        setAsked({ prompt, failed: false });
        if (first && prompt.chat && prompt.chat.kind !== "unknown" && !prompt.chat.delivered) timer = window.setTimeout(() => look(false), LOOK_AGAIN_MS);
      }, () => { if (alive && first) setAsked({ prompt: null, failed: true }); });
    };
    look(true);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [projectId, taskRef, answered]);

  const loading = asked.prompt === null && !asked.failed;
  const chat = asked.prompt?.chat ?? UNKNOWN_CHAT;
  const known = !loading && chat.kind !== "unknown";
  const preferred: AgentName = asked.prompt?.agent ?? "claude";
  const other: AgentName = preferred === "claude" ? "codex" : "claude";

  /** Start a new chat with the prompt typed in. */
  async function open(agent: AgentName) {
    setBusy(true); setError(null);
    try {
      const prompt = asked.prompt && asked.prompt.agent === agent ? asked.prompt : await reviewsApi.fixPrompt(projectId, taskRef, agent);
      let copied = false;
      try { await navigator.clipboard.writeText(prompt.prompt); copied = true; } catch { /* said below instead */ }
      const opener = window.projectBrainDesktop?.openAgent;
      const opened = opener ? await opener(prompt.url) : false;
      setResult({ prompt, agent: prompt.agent, opened, copied });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("The prompt could not be prepared."));
    } finally { setBusy(false); }
  }

  /** Open the chat that asked, in the app that runs it. */
  async function goToChat() {
    setBusy(true); setError(null);
    let opened = false;
    try {
      const opener = window.projectBrainDesktop?.openAgent;
      opened = chat.url && opener ? await opener(chat.url) : false;
    } catch { /* said below: it could not be opened */ }
    setResult({ prompt: null, agent: chat.agent ?? preferred, opened, copied: false });
    setBusy(false);
  }

  async function copyResume() {
    try { await navigator.clipboard.writeText(chat.resume ?? ""); } catch { return; }
    setResumeCopied(true);
    window.setTimeout(() => setResumeCopied(false), 2000);
  }

  const canOpen = chat.kind === "desktop" || chat.kind === "codex";
  // One sentence says where the decision goes and whether it arrived; the chat that did the work is "the chat that asked" for an answer.
  const intro = loading ? null
    : known
      ? (answered
        ? (chat.delivered ? t("Your answer is already in the chat that asked.") : t("Your answer goes to the chat that asked as soon as it can take it."))
        : (chat.delivered ? t("Your comments are already in the chat that did the work.") : t("Your comments go to the chat that did the work as soon as it can take them.")))
      : (answered ? t("The next agent that opens this project sees your answer first. Or hand it over now:") : t("The next agent that opens this project sees your comments first. Or hand them over now:"));

  return (
    <div className={compact ? "" : `rounded-xl border p-3 ${answered ? "border-info/30 bg-info-soft/60" : "border-danger/30 bg-danger-soft/60"}`}>
      {(!compact || known) && (
        <p role={known ? "status" : undefined} className="text-sm text-ink">
          {!compact && <strong className={answered ? "text-info-ink" : "text-danger-ink"}>{answered ? t("Answered.") : t("Sent back.")}</strong>}
          {intro && <>{!compact && " "}{intro}</>}
        </p>
      )}
      {!loading && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
          {canOpen && <Button variant="primary" size="sm" disabled={busy} onClick={() => void goToChat()}><Bot size={15} aria-hidden="true" />{t("Go to the chat")}</Button>}
          {!known && <Button variant="primary" size="sm" disabled={busy} onClick={() => void open(preferred)}><Bot size={15} aria-hidden="true" />{busy ? t("Preparing…") : answered ? t("Start a new chat in {agent} with my answer", { agent: NAME[preferred] }) : t("Start a new chat in {agent} with my comments", { agent: NAME[preferred] })}</Button>}
          {!known && <button type="button" disabled={busy} onClick={() => void open(other)} className="text-sm font-semibold text-forest hover:underline disabled:opacity-50">{t("or in {agent}", { agent: NAME[other] })}</button>}
          {known && <button type="button" disabled={busy} onClick={() => void open(chat.agent ?? preferred)} className="text-xs font-medium text-ink-muted underline hover:text-ink disabled:opacity-50">{t("Start a new chat instead")}</button>}
        </div>
      )}
      {known && !canOpen && <p className="mt-2 text-xs text-ink-muted">{t("Moah can't open that chat from here: it runs in a terminal or outside the Claude app.")}</p>}
      {known && chat.resume && (
        <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
          <span>{t("Or in a terminal:")}</span>
          <code className="select-all rounded bg-neutral-soft px-1.5 py-0.5 font-mono text-ink">{chat.resume}</code>
          <button type="button" onClick={() => void copyResume()} aria-label={t("Copy command")} className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-medium hover:bg-hover focus-visible:outline-2 focus-visible:outline-forest">{resumeCopied ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}{resumeCopied ? t("Copied") : t("Copy")}</button>
        </p>
      )}
      {result && (result.prompt !== null || !result.opened) && (
        <p role="status" className="mt-2 text-xs text-ink-muted">
          {result.opened ? t("{agent} opened with the prompt typed in. Read it, then press Enter to start.", { agent: NAME[result.agent] }) : t("{agent} could not be opened from here.", { agent: NAME[result.agent] })}
          {result.copied ? ` ${t("The prompt is also on your clipboard.")}` : ""}
          {result.prompt?.agent === "claude" && result.opened && result.prompt.folder ? ` ${t("Choose the folder {folder} in Claude before sending.", { folder: result.prompt.folder })}` : ""}
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
  const shortcut = useDictationShortcut();
  if (!canDictate) return null;
  const listening = dictation.phase === "recording";
  const finishing = dictation.phase === "transcribing" || dictation.phase === "starting";
  return (
    <Button size="sm" variant={listening ? "danger" : "secondary"} onMouseDown={(event) => event.preventDefault()} disabled={finishing}
      onClick={() => { field.current?.focus(); toggleDictation(); }} aria-pressed={listening} aria-keyshortcuts={shortcutAria(shortcut)}
      title={`${listening ? t("Stop dictating") : t("Dictate your comment")} (${shortcutLabel(shortcut)})`}>
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
 * (the task moves to Done; a comment or a file goes to the chat that did the work, and accepting
 * without one wakes nobody) or send it back (your comments go to the agent and the task goes back
 * to In progress). Sending back needs a comment or a file, so the agent knows what to fix. For an
 * agent's question, the box takes your answer instead.
 */
export function ReviewComposer({ detail, quote, criteria, onDecided, onUndone }: { detail: ReviewDetail; quote: Quoted | null; criteria: { id: string; met: boolean }[]; onDecided: (verdict: ReviewDecisionInput["verdict"], result: ReviewDetail) => void; onUndone?: (detail: ReviewDetail) => void }) {
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

  async function undo() {
    try {
      await reviewsApi.undo(detail.project_id, detail.task_ref);
      notify(t("Undone. {task} waits in Review again.", { task: detail.task_ref }), "success", { group: "review-decision" });
      onUndone?.(detail);
    } catch (cause) {
      notify(cause instanceof Error ? cause.message : t("It could not be undone."), "danger", { group: "review-decision" });
    } finally {
      await client.invalidateQueries();
    }
  }

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
        if (verdict === "accept") {
          // One notice for a run of accepts, each with a way to take it back. A comment (or a file)
          // goes to the chat that did the work when Moah knows it; when it does not, say that it
          // stays under Reviewed instead (the brief never shows a Done task, so no agent is next).
          const accepted = t("Accepted. {task} is in Done.", { task: detail.task_ref });
          const where = result.current.chat_known
            ? t("Your comment goes to the chat that did the work.")
            : t("Moah doesn't know which chat did the work, so your comment is only saved under Reviewed.");
          notify(said ? `${accepted} ${where}` : accepted, "success", {
            group: "review-decision",
            action: { label: t("Undo"), run: () => undo() },
          });
        } else {
          notify(verdict === "approve" ? t("Approved. {task} is back in progress.", { task: detail.task_ref })
            : verdict === "answer" ? t("Answer sent. {task} is back in progress.", { task: detail.task_ref }) : t("Sent back. {task} is in progress again, with your comments.", { task: detail.task_ref }),
          "success", { group: "review-decision" });
        }
        onDecided(verdict, result);
      },
    });
  }

  // Keys for going through a pile without the mouse: A accepts finished work and moves on, S puts
  // you in the comment box to send it back (or answer). Never while you type, or with a modifier.
  const singleKeys = useSingleKeys();
  const keys = useRef({ send, question, busy, singleKeys });
  keys.current = { send, question, busy, singleKeys };
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const now = keys.current;
      if (!now.singleKeys || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest(TYPING)) return;
      const key = event.key.toLowerCase();
      if (key === "a" && !now.question && !now.busy) {
        event.preventDefault();
        now.send("accept");
      } else if (key === "s") {
        event.preventDefault();
        field.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div data-keep-clear="" onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}
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
          <Button variant="primary" disabled={busy} onClick={() => send("accept")} aria-keyshortcuts={singleKeys ? "A" : undefined} title={singleKeys ? t("The task moves to Done. You can still reopen it from Reviewed. Key: A") : t("The task moves to Done. You can still reopen it from Reviewed.")}>
            <Check size={16} aria-hidden="true" />{t("Accept and move to Done")}
          </Button>
        </>}
      </div>
      {!question && singleKeys && <p className="mt-2 hidden text-xs text-ink-subtle sm:block">{t("Keys: A accepts and opens the next, S starts a comment, J and K move through the list.")}</p>}
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
      <div data-keep-clear="" className="flex justify-end border-t border-line bg-surface px-5 py-3">
        <Button variant="secondary" onClick={() => setOpen(true)} title={t("The task goes back to In progress, and the next agent reads your comment first.")}><RotateCcw size={15} aria-hidden="true" />{t("Reopen with a comment")}</Button>
      </div>
    );
  }
  return (
    <div data-keep-clear="" className="border-t border-line bg-surface px-5 pb-4 pt-3">
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
