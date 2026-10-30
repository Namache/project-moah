import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { settingsApi } from "../api/settings";
import { queryKeys } from "../lib/queries";
import { locale, t } from "../lib/i18n";

/** The switch that deletes tasks two weeks after they were completed. Activity keeps the record. */
export function TaskSettingsCard() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: queryKeys.taskSettings, queryFn: ({ signal }) => settingsApi.tasks(signal), retry: false });
  const save = useMutation({
    mutationFn: (on: boolean) => settingsApi.updateTasks({ auto_delete_done: on }),
    onSuccess: (data) => client.setQueryData(queryKeys.taskSettings, data),
  });
  const s = query.data;
  if (query.isError) return <p role="alert" className="text-sm text-danger-ink">{t("Task settings are unavailable:")} {query.error.message}</p>;
  if (!s) return <p role="status" className="text-sm text-ink-muted">{t("Loading task settings…")}</p>;
  const since = s.auto_delete_done && s.auto_delete_done_since ? new Date(s.auto_delete_done_since) : null;
  const firstRun = since ? new Date(since.getTime() + 14 * 24 * 60 * 60 * 1000) : null;

  return (
    <div className="space-y-2">
      <label className="flex items-start gap-3 text-sm text-ink">
        <input type="checkbox" className="mt-0.5 h-4 w-4 accent-primary" checked={s.auto_delete_done} disabled={save.isPending} onChange={(e) => save.mutate(e.target.checked)} />
        <span><strong>{t("Delete completed tasks after two weeks")}</strong><br /><span className="text-ink-muted">{t("A task that has been in Completed for two weeks is deleted for good. The activity log keeps what was done: the task's id, title, and when it was completed. Archived tasks are kept.")}</span></span>
      </label>
      {firstRun && firstRun > new Date() && <p className="pl-7 text-xs text-ink-subtle">{t("Counting from when you turned this on: nothing is deleted before {date}.", { date: firstRun.toLocaleDateString(locale()) })}</p>}
      {save.isError && <p role="alert" className="text-sm text-danger-ink">{save.error.message}</p>}
    </div>
  );
}
