import { useState } from "react";
import { useReviewActions } from "../../hooks/useProposals";
import { Button } from "../ui";

/** "Accept all" for one project's waiting suggestions, with a confirmation step and a note when some could not be applied. */
export function AcceptAllButton({ projectId, count, label = "Accept all" }: { projectId: string; count: number; label?: string }) {
  const [confirming, setConfirming] = useState(false);
  const { acceptAll } = useReviewActions(projectId);
  const failed = acceptAll.data?.failed.length ?? 0;
  return (
    <>
      {confirming
        ? <span className="flex items-center gap-2 text-sm">Accept all {count}? <Button variant="primary" disabled={acceptAll.isPending} onClick={() => acceptAll.mutate(undefined, { onSettled: () => setConfirming(false) })}>Yes, accept all</Button><Button variant="quiet" onClick={() => setConfirming(false)}>Cancel</Button></span>
        : <Button onClick={() => setConfirming(true)}>{label}</Button>}
      {failed > 0 && <p role="alert" className="basis-full rounded-xl bg-warning-soft px-4 py-3 text-sm text-warning-ink">{acceptAll.data!.accepted.length} accepted. {failed} could not be applied and {failed === 1 ? "is" : "are"} still waiting, with the reason shown on each.</p>}
    </>
  );
}
