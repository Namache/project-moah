import { useQuery } from "@tanstack/react-query";
import { agentsApi } from "../api/agents";
import { queryKeys } from "./queries";

/** Where a single-letter key types instead of acting. A checkbox doesn't type, so A still works
 * after you tick an acceptance criterion. */
export const TYPING = "textarea, input:not([type='checkbox']), select, [contenteditable='true'], [role='dialog']";

/** Whether Review's single-letter keys (A, S, J, K) are on: Settings > Accessibility can turn
 * them off, for speech input, which "types" letters that would otherwise accept work. On until
 * the settings say otherwise. Arrow keys and buttons keep working either way. */
export function useSingleKeys(): boolean {
  const query = useQuery({ queryKey: queryKeys.agentSettings, queryFn: ({ signal }) => agentsApi.settings(signal), retry: false });
  return query.data?.review_single_keys !== false;
}
