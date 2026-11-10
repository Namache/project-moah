/** Screenshots and text files attached to a review, and the lightbox that shows them. */
import { useEffect, useState } from "react";
import { Camera, ChevronLeft, ChevronRight, FileText, MessageSquareQuote, X } from "lucide-react";
import type { ReviewFile } from "../../types/review";
import { useModalDialog } from "../../hooks/useModalDialog";
import { t } from "../../lib/i18n";
import { Button } from "../ui";
import { type Quote, useReviewFileUrl } from "./reviewBits";

function Lightbox({ projectId, files, index, onIndex, onClose, onQuote }: { projectId: string; files: ReviewFile[]; index: number; onIndex: (index: number) => void; onClose: () => void; onQuote?: Quote }) {
  const ref = useModalDialog();
  const file = files[index];
  const url = useReviewFileUrl(projectId, file.id);
  const label = file.caption || file.filename;
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "ArrowRight") onIndex((index + 1) % files.length);
      if (event.key === "ArrowLeft") onIndex((index - 1 + files.length) % files.length);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, files.length, onIndex]);
  return (
    <dialog ref={ref} onCancel={(event) => { event.preventDefault(); onClose(); }} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }} aria-label={label}
      className="m-auto h-[94vh] w-[94vw] max-w-none rounded-xl border border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-black/75">
      <div className="flex h-full flex-col">
        <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
          <Camera size={16} className="text-forest" aria-hidden="true" />
          <p className="min-w-0 flex-1 truncate text-sm font-semibold">{label}</p>
          <span className="text-xs tabular-nums text-ink-subtle">{t("{index} of {total}", { index: index + 1, total: files.length })}</span>
          {onQuote && <Button size="sm" variant="quiet" onClick={() => { onQuote(t("Screenshot “{name}”:", { name: label })); onClose(); }}><MessageSquareQuote size={15} aria-hidden="true" />{t("Comment on this")}</Button>}
          <Button size="icon" onClick={onClose} aria-label={t("Close image")}><X className="h-4 w-4" aria-hidden="true" /></Button>
        </div>
        <div className="relative flex min-h-0 flex-1 items-center justify-center bg-canvas p-4">
          {url ? <img src={url} alt={label} className="max-h-full max-w-full rounded-md object-contain shadow-card" /> : <p role="status" className="text-sm text-ink-muted">{t("Loading image…")}</p>}
          {files.length > 1 && <>
            <Button size="icon" className="absolute left-3 top-1/2 -translate-y-1/2 bg-surface/90" onClick={() => onIndex((index - 1 + files.length) % files.length)} aria-label={t("Previous screenshot")}><ChevronLeft className="h-5 w-5" aria-hidden="true" /></Button>
            <Button size="icon" className="absolute right-3 top-1/2 -translate-y-1/2 bg-surface/90" onClick={() => onIndex((index + 1) % files.length)} aria-label={t("Next screenshot")}><ChevronRight className="h-5 w-5" aria-hidden="true" /></Button>
          </>}
        </div>
      </div>
    </dialog>
  );
}

function Shot({ projectId, file, onOpen, small = false }: { projectId: string; file: ReviewFile; onOpen: () => void; small?: boolean }) {
  const url = useReviewFileUrl(projectId, file.id);
  const label = file.caption || file.filename;
  return (
    <li className="min-w-0">
      <button type="button" onClick={onOpen} aria-label={t("View {name}", { name: label })}
        className={`group block w-full overflow-hidden rounded-lg border border-line bg-canvas text-left shadow-card transition hover:-translate-y-0.5 hover:shadow-card-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-forest`}>
        <span className={`block ${small ? "aspect-[4/3]" : "aspect-video"} overflow-hidden bg-neutral-soft`}>
          {url ? <img src={url} alt="" className="h-full w-full object-cover object-top transition-transform group-hover:scale-[1.02]" /> : null}
        </span>
        {!small && <span className="block truncate border-t border-line px-2.5 py-1.5 text-xs text-ink-muted">{label}</span>}
      </button>
    </li>
  );
}

function TextFile({ projectId, file }: { projectId: string; file: ReviewFile }) {
  const url = useReviewFileUrl(projectId, file.id);
  return (
    <li>
      <a href={url ?? undefined} download={file.filename} className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs font-medium text-ink hover:border-forest hover:text-forest">
        <FileText size={14} aria-hidden="true" />{file.filename}
      </a>
    </li>
  );
}

export function Gallery({ projectId, files, onQuote, small = false }: { projectId: string; files: ReviewFile[]; onQuote?: Quote; small?: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  const images = files.filter((f) => f.media_type.startsWith("image/"));
  const texts = files.filter((f) => !f.media_type.startsWith("image/"));
  return (
    <>
      {images.length > 0 && <ul className={`grid gap-3 ${small ? "grid-cols-[repeat(auto-fill,minmax(6rem,1fr))]" : "grid-cols-[repeat(auto-fill,minmax(14rem,1fr))]"}`}>{images.map((file, index) => <Shot key={file.id} projectId={projectId} file={file} small={small} onOpen={() => setOpen(index)} />)}</ul>}
      {texts.length > 0 && <ul className="mt-2 flex flex-wrap gap-2">{texts.map((file) => <TextFile key={file.id} projectId={projectId} file={file} />)}</ul>}
      {open !== null && images[open] && <Lightbox projectId={projectId} files={images} index={open} onIndex={setOpen} onClose={() => setOpen(null)} onQuote={onQuote} />}
    </>
  );
}
