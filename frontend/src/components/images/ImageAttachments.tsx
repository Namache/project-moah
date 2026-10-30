import { useEffect, useRef, useState, type DragEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ImagePlus, X } from "lucide-react";
import { imagesApi } from "../../api/images";
import { invalidateProject } from "../../lib/queries";
import { useModalDialog } from "../../hooks/useModalDialog";
import { IMAGE_TYPES, MAX_IMAGE_BYTES, MAX_IMAGES_PER_RECORD, type ImageInfo, type ImageOwner } from "../../types/image";
import { Button, ConfirmDialog } from "../ui";
import { notify } from "../../lib/notify";
import { t } from "../../lib/i18n";

/** Loads one attached image as an object URL, released when the image leaves the screen. */
function useImageUrl(projectId: string, imageId: string): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let made: string | null = null;
    imagesApi.blob(projectId, imageId, controller.signal).then((blob) => { made = URL.createObjectURL(blob); setUrl(made); }).catch(() => setUrl(null));
    return () => { controller.abort(); if (made) URL.revokeObjectURL(made); };
  }, [projectId, imageId]);
  return url;
}

function Viewer({ projectId, image, onClose }: { projectId: string; image: ImageInfo; onClose: () => void }) {
  const ref = useModalDialog();
  const url = useImageUrl(projectId, image.id);
  return (
    <dialog ref={ref} onCancel={(event) => { event.preventDefault(); onClose(); }} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }} aria-label={image.filename} className="m-auto max-h-[90vh] max-w-[90vw] rounded-xl border border-line bg-surface p-3 text-ink shadow-dialog backdrop:bg-black/60">
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="truncate text-sm font-semibold">{image.filename}</p>
        <Button size="icon" onClick={onClose} aria-label={t("Close image")}><X className="h-4 w-4" aria-hidden="true" /></Button>
      </div>
      {url ? <img src={url} alt={image.filename} className="max-h-[80vh] max-w-full object-contain" /> : <p role="status" className="text-sm text-ink-muted">{t("Loading image…")}</p>}
    </dialog>
  );
}

function Thumb({ projectId, image, readOnly, onOpen, onRemove }: { projectId: string; image: ImageInfo; readOnly: boolean; onOpen: () => void; onRemove: () => void }) {
  const url = useImageUrl(projectId, image.id);
  return (
    <li className="group relative h-24 w-24 overflow-hidden rounded-lg border border-line bg-hover">
      <button type="button" onClick={onOpen} aria-label={t("View {name}", { name: image.filename })} className="h-full w-full focus-visible:outline-2 focus-visible:outline-forest">
        {url && <img src={url} alt="" className="h-full w-full object-cover" />}
      </button>
      {!readOnly && <button type="button" onClick={onRemove} aria-label={t("Remove {name}", { name: image.filename })} className="absolute right-1 top-1 rounded-full bg-surface/90 p-1 text-ink-muted opacity-0 shadow hover:text-danger-ink focus-visible:opacity-100 group-hover:opacity-100"><X className="h-3.5 w-3.5" aria-hidden="true" /></button>}
    </li>
  );
}

function problemWith(file: File): string | null {
  if (!IMAGE_TYPES.includes(file.type)) return file.name ? t("{name} is not a PNG, JPEG, WebP or GIF image.", { name: file.name }) : t("That file is not a PNG, JPEG, WebP or GIF image.");
  if (file.size > MAX_IMAGE_BYTES) return t("{name} is larger than 5 MB.", { name: file.name });
  return null;
}

/**
 * The images of one task or memory record. Add them by dropping files here, pasting with
 * Ctrl+V anywhere in the open panel, or browsing. Agents see them through brain_view_images.
 */
export function ImageAttachments({ projectId, owner, record, images, readOnly = false }: { projectId: string; owner: ImageOwner; record: string; images: ImageInfo[]; readOnly?: boolean }) {
  const client = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<ImageInfo | null>(null);
  const [removing, setRemoving] = useState<ImageInfo | null>(null);
  const room = MAX_IMAGES_PER_RECORD - images.length;

  async function add(files: File[]) {
    if (readOnly || !files.length) return;
    setError(null);
    const problems = files.map(problemWith).filter(Boolean);
    const good = files.filter((file) => !problemWith(file)).slice(0, Math.max(room, 0));
    if (files.length - problems.length > good.length) problems.push(t("Each task or memory can hold {count} images.", { count: MAX_IMAGES_PER_RECORD }));
    setBusy(true);
    try {
      for (const file of good) {
        await imagesApi.attach(projectId, owner, record, file, file.name);
      }
    } catch (failure) {
      problems.push(failure instanceof Error ? failure.message : t("The image could not be attached."));
    } finally {
      setBusy(false);
      if (problems.length) setError(problems.join(" "));
      if (good.length) await invalidateProject(client, projectId);
    }
  }

  async function remove(image: ImageInfo) {
    setRemoving(null);
    setError(null);
    try {
      await imagesApi.remove(projectId, image.id);
      await invalidateProject(client, projectId);
      notify(t("{name} removed", { name: image.filename }));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : t("The image could not be removed."));
    }
  }

  // A pasted image goes to the open record, wherever focus is; pasted text is left alone.
  const addRef = useRef(add);
  addRef.current = add;
  useEffect(() => {
    if (readOnly) return;
    function paste(event: ClipboardEvent) {
      const files = Array.from(event.clipboardData?.files ?? []).filter((file) => file.type.startsWith("image/"));
      if (!files.length) return;
      event.preventDefault();
      void addRef.current(files.map((file) => file.name ? file : new File([file], t("pasted image"), { type: file.type })));
    }
    document.addEventListener("paste", paste);
    return () => document.removeEventListener("paste", paste);
  }, [readOnly]);

  function drop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    void add(Array.from(event.dataTransfer.files));
  }

  return (
    <div onDragOver={(event) => { if (readOnly) return; event.preventDefault(); setDragging(true); }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }} onDrop={readOnly ? undefined : drop}>
      {images.length > 0 && <ul className="mb-3 flex flex-wrap gap-2" aria-label={t("Attached images")}>{images.map((image) => <Thumb key={image.id} projectId={projectId} image={image} readOnly={readOnly} onOpen={() => setViewing(image)} onRemove={() => setRemoving(image)} />)}</ul>}
      {!readOnly && room > 0 && (
        <div className={`flex flex-wrap items-center gap-3 rounded-xl border border-dashed px-4 py-3 text-sm ${dragging ? "border-forest bg-sage-pale text-ink" : "border-line-strong text-ink-muted"}`}>
          <ImagePlus className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="flex-1">{busy ? t("Attaching…") : t("Drop images here or paste one with Ctrl+V.")}</span>
          <Button size="sm" disabled={busy} onClick={() => input.current?.click()}>{t("Browse…")}</Button>
          <input ref={input} type="file" accept={IMAGE_TYPES.join(",")} multiple hidden aria-label={t("Choose images")} onChange={(event) => { void add(Array.from(event.target.files ?? [])); event.target.value = ""; }} />
        </div>
      )}
      {readOnly && !images.length && <p className="text-sm text-ink-subtle">{t("No images.")}</p>}
      {error && <p role="alert" className="mt-2 text-sm text-danger-ink">{error}</p>}
      {viewing && <Viewer projectId={projectId} image={viewing} onClose={() => setViewing(null)} />}
      {removing && <ConfirmDialog title={t("Remove {name}?", { name: removing.filename })} confirmLabel={t("Remove image")} onConfirm={() => void remove(removing)} onClose={() => setRemoving(null)}>{t("The image is deleted from Project Moah. This can't be undone.")}</ConfirmDialog>}
    </div>
  );
}
