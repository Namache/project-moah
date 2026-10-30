import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

export type ParamChanges = Record<string, string | null | undefined>;

/**
 * The page's query parameters plus one updater that changes several keys at once.
 * React Router's updater reads the parameters from the last render, so two separate updates in one
 * event would overwrite each other; passing every change in a single call avoids that.
 * Updates replace the history entry, so filters do not fill the back button.
 */
export function useUrlParams(): [URLSearchParams, (changes: ParamChanges) => void] {
  const [params, setParams] = useSearchParams();
  const update = useCallback((changes: ParamChanges) => setParams((current) => {
    const next = new URLSearchParams(current);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    return next;
  }, { replace: true }), [setParams]);
  return [params, update];
}
