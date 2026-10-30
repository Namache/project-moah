import { useSyncExternalStore } from "react";

export type NoticeTone = "success" | "danger" | "neutral";
export interface Notice { id: number; message: string; tone: NoticeTone }

let notices: Notice[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

export function dismissNotice(id: number) {
  notices = notices.filter((notice) => notice.id !== id);
  emit();
}

/** Shows a short notice in the corner: "Saved", "Couldn't save...". It goes away by itself after a few seconds. */
export function notify(message: string, tone: NoticeTone = "success") {
  const id = nextId++;
  notices = [...notices.slice(-2), { id, message, tone }];
  emit();
  setTimeout(() => dismissNotice(id), tone === "danger" ? 8000 : 3500);
}

export function useNotices(): Notice[] {
  return useSyncExternalStore((onChange) => { listeners.add(onChange); return () => listeners.delete(onChange); }, () => notices);
}
