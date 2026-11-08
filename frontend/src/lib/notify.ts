import { useSyncExternalStore } from "react";

export type NoticeTone = "success" | "danger" | "neutral";
export interface NoticeAction { label: string; run: () => void | Promise<void> }
export interface Notice { id: number; message: string; tone: NoticeTone; group?: string; action?: NoticeAction }
export interface NoticeOptions {
  /** A new notice of the same group takes the place of the last one instead of piling up. */
  group?: string;
  /** One button on the notice, such as Undo. It stays longer, so there is time to press it. */
  action?: NoticeAction;
}

let notices: Notice[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

export function dismissNotice(id: number) {
  notices = notices.filter((notice) => notice.id !== id);
  emit();
}

/** Shows a short notice in the corner: "Saved", "Couldn't save...". It goes away by itself after a few seconds. */
export function notify(message: string, tone: NoticeTone = "success", options: NoticeOptions = {}) {
  const id = nextId++;
  const { group, action } = options;
  const kept = group ? notices.filter((notice) => notice.group !== group) : notices;
  notices = [...kept.slice(-2), { id, message, tone, group, action }];
  emit();
  setTimeout(() => dismissNotice(id), tone === "danger" || action ? 8000 : 3500);
}

export function useNotices(): Notice[] {
  return useSyncExternalStore((onChange) => { listeners.add(onChange); return () => listeners.delete(onChange); }, () => notices);
}
