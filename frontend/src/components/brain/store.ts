import { create } from "zustand";

/** Live Brain View state, kept out of React renders so the render loop can read it cheaply. */
interface BrainState {
  selected: string | null;
  hovered: string | null;
  focusShelf: string | null;
  showGuesses: boolean;
  select: (key: string | null) => void;
  hover: (key: string | null) => void;
  setFocusShelf: (id: string | null) => void;
  setShowGuesses: (value: boolean) => void;
}

export const useBrainStore = create<BrainState>((set) => ({
  selected: null,
  hovered: null,
  focusShelf: null,
  showGuesses: false,
  select: (selected) => set({ selected }),
  hover: (hovered) => set({ hovered }),
  setFocusShelf: (focusShelf) => set({ focusShelf }),
  setShowGuesses: (showGuesses) => set({ showGuesses }),
}));
