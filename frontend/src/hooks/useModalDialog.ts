import { useEffect, useRef, type RefObject } from "react";

/**
 * Opens a native <dialog> when the component mounts and closes it when it unmounts.
 * Modal dialogs trap focus and cover the page; pass modal=false to open one beside the page instead.
 * The choice is made once, when the dialog opens.
 */
export function useModalDialog(modal = true): RefObject<HTMLDialogElement | null> {
  const ref = useRef<HTMLDialogElement>(null);
  const openModal = useRef(modal);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) {
      if (openModal.current) dialog.showModal();
      else dialog.show();
    }
    return () => { if (dialog?.open) dialog.close(); };
  }, []);
  return ref;
}
