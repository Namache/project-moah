import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderSearch, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { agentFoldersApi, type AgentFolder, type FolderStatus } from "../api/agentFolders";
import { Button } from "./ui";
import { invalidateWorkspace, queryKeys } from "../lib/queries";
import { projectPath } from "../lib/routes";

const STATUS: Record<FolderStatus, string> = { created: "Project created", linked: "Linked", suggested: "Waiting for you", ignored: "Ignored" };
const sessions = (f: AgentFolder) => [f.claude_sessions && `${f.claude_sessions} Claude Code`, f.codex_sessions && `${f.codex_sessions} Codex`].filter(Boolean).join(", ") + " sessions";
const shortPath = (folder: string) => folder.replace(/^\/(var\/)?home\/[^/]+/, "~");

/** The folders Claude Code and Codex worked in, refreshed every minute. */
export function useAgentFolders() {
  return useQuery({ queryKey: queryKeys.agentFolders, queryFn: ({ signal }) => agentFoldersApi.sync(signal), refetchInterval: 60_000, retry: false });
}

/**
 * Sync from agents: projects come from the folders Claude Code and Codex work in.
 * With folders waiting for an answer it is a full panel; otherwise it shrinks to one quiet line.
 */
export function AgentSync() {
  const client = useQueryClient();
  const query = useAgentFolders();
  const [error, setError] = useState<string | null>(null);
  const refreshProjects = () => Promise.all([invalidateWorkspace(client), client.invalidateQueries({ queryKey: ["project"] })]);
  const created = query.data?.created?.length ?? 0;
  useEffect(() => { if (created) void refreshProjects(); }, [created, query.dataUpdatedAt]); // eslint-disable-line react-hooks/exhaustive-deps
  const decide = useMutation({
    mutationFn: ({ folder, action, projectId }: { folder: string; action: "link" | "create" | "ignore"; projectId?: string }) => agentFoldersApi.decide(folder, action, projectId),
    onSuccess: (data) => { client.setQueryData(queryKeys.agentFolders, data); void refreshProjects(); setError(null); },
    onError: (cause) => setError(cause instanceof Error ? cause.message : "That answer could not be saved."),
  });
  const folders = Array.isArray(query.data?.folders) ? query.data.folders : [];
  const waiting = folders.filter((f) => f.status === "suggested");

  const syncButton = <Button variant="quiet" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw size={15} className={query.isFetching ? "animate-spin" : ""} aria-hidden="true" />{query.isFetching ? "Syncing" : "Sync now"}</Button>;
  const alerts = <>
    {query.isError && <p role="alert" className="mt-3 text-sm text-danger-ink">Sync is unavailable: {query.error.message}</p>}
    {error && <p role="alert" className="mt-3 text-sm text-danger-ink">{error}</p>}
  </>;
  const folderList = folders.length > 0 && (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer font-semibold text-forest">{folders.length} {folders.length === 1 ? "folder" : "folders"} found</summary>
      <ul className="mt-2 divide-y divide-line">
        {folders.map((f) => (
          <li key={f.folder} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
            <div className="min-w-0">
              <p className="break-all text-ink">{shortPath(f.folder)}</p>
              <p className="text-xs text-ink-subtle">{sessions(f)}</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="rounded-full bg-canvas px-2 py-0.5 text-xs text-ink-muted">{STATUS[f.status]}</span>
              {f.project_id && f.status !== "suggested" && <Link to={projectPath(f.project_id)} className="text-xs font-semibold text-forest hover:underline">{f.project_name}</Link>}
              {f.status === "ignored" && <Button variant="quiet" onClick={() => decide.mutate({ folder: f.folder, action: "create" })} disabled={decide.isPending}>Make a project</Button>}
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs leading-5 text-ink-subtle">Only the folder each session started in is read, never what was said. Files and Git views still need the folder shared with Project Moah; use Choose folder in a project's settings.</p>
    </details>
  );

  if (waiting.length === 0) {
    return (
      <section aria-labelledby="agent-sync-title" className="mt-10 border-t border-line pt-5">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            <h2 id="agent-sync-title" className="flex items-center gap-2 text-sm font-semibold text-ink"><FolderSearch size={16} className="text-forest" aria-hidden="true" />Sync from agents</h2>
            <p className="mt-0.5 text-xs text-ink-muted">Folders you open in Claude Code or Codex become projects automatically. Temporary folders and one-off chats are skipped.</p>
          </div>
          {syncButton}
        </div>
        {alerts}
        {folderList}
      </section>
    );
  }

  return (
    <section aria-labelledby="agent-sync-title" className="mt-6 rounded-xl border border-warning/40 bg-surface p-5 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="agent-sync-title" className="flex items-center gap-2 text-base font-semibold text-ink"><FolderSearch size={17} className="text-forest" aria-hidden="true" />{waiting.length === 1 ? "A new folder needs your answer" : `${waiting.length} new folders need your answer`}</h2>
          <p className="mt-1 text-sm text-ink-muted">Claude Code or Codex worked in {waiting.length === 1 ? "a folder" : "folders"} that might belong to a project you already have.</p>
        </div>
        {syncButton}
      </div>
      {alerts}

      {waiting.map((f) => (
        <div key={f.folder} className="mt-4 rounded-xl border border-warning/40 bg-warning-soft p-4">
          <p className="text-sm font-semibold text-ink">Is this {f.project_name}'s folder?</p>
          <p className="mt-1 break-all text-sm text-ink-muted">{shortPath(f.folder)}</p>
          <p className="mt-0.5 text-xs text-ink-subtle">{sessions(f)}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => decide.mutate({ folder: f.folder, action: "link", projectId: f.project_id ?? undefined })} disabled={decide.isPending}>Yes, it is {f.project_name}</Button>
            <Button onClick={() => decide.mutate({ folder: f.folder, action: "create" })} disabled={decide.isPending}>No, make a new project</Button>
            <Button variant="quiet" onClick={() => decide.mutate({ folder: f.folder, action: "ignore" })} disabled={decide.isPending}>Ignore this folder</Button>
          </div>
        </div>
      ))}

      {folderList}
    </section>
  );
}
