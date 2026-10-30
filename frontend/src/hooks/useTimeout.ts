import { useCallback, useEffect, useRef } from "react";

/**
 * Returns a function that runs a callback after a delay. A new call replaces the pending one,
 * and nothing runs once the component has unmounted.
 */
export function useTimeout(): (callback: () => void, ms: number) => void {
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return useCallback((callback: () => void, ms: number) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(callback, ms);
  }, []);
}
