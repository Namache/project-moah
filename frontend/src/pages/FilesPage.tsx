import { FolderOpen } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useUrlParams } from "../hooks/useUrlParams";
import { Commits, GitBanner } from "../components/files/GitPanel";
import { FileDetail } from "../components/files/FileDetail";
import { FileTreeView } from "../components/files/FileTreeView";
import { EmptyState, ErrorState, buttonBase, buttonClasses } from "../components/ui";
import { useFileTree } from "../hooks/useFiles";
import { t } from "../lib/i18n";

export function FilesPage({ projectId, archived }: { projectId: string; archived: boolean }) {
  const [params, updateParams] = useUrlParams();
  const [filter, setFilter] = useState("");
  const tree = useFileTree(projectId);
  const selected = params.get("file");
  if (tree.isPending) return <div role="status" aria-label={t("Loading files")} className="h-72 animate-pulse rounded-xl bg-surface" />;
  if (tree.isError) return <ErrorState title={t("Files could not be loaded")} message={tree.error.message} onRetry={() => void tree.refetch()} />;
  const { git, entries, source, truncated } = tree.data;
  const entry = entries.find((e) => e.path === selected) ?? null;
  const select = (path: string | null) => updateParams({ file: path });

  return (
    <div className="space-y-6">
      <GitBanner git={git} />
      {entries.length === 0 ? (
        <EmptyState icon={<FolderOpen size={26} />} title={t("No files to show yet")} action={<Link to="/help/files-and-git" className={`${buttonBase} ${buttonClasses.secondary}`}>{t("Learn about files and Git")}</Link>}>
          {git.state === "no_path" ? t("Add a repository folder to this project to browse its files here. File notes help agents open the right file first.") : t("Project Moah shows a repository's files here, with notes about what each one is for. It stores notes, never your source code.")}
        </EmptyState>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
          <section aria-label={t("Repository files")} className="rounded-xl border border-line bg-surface p-3 shadow-card">
            <label htmlFor="file-filter" className="sr-only">{t("Filter files")}</label>
            <input id="file-filter" className="field-input !min-h-9" placeholder={t("Filter files")} value={filter} onChange={(e) => setFilter(e.target.value)} />
            <div className="mt-2 max-h-[34rem] overflow-y-auto pr-1"><FileTreeView entries={entries} selected={selected} onSelect={select} filter={filter} /></div>
            <p className="mt-2 px-1 text-xs text-ink-subtle">{source === "notes" ? t("Showing only files with notes.") : source === "folder" ? t("Listing the folder directly.") : t("Listing files tracked by Git.")}{truncated && ` ${t("The list was shortened.")}`}</p>
          </section>
          <div>{entry ? <FileDetail key={entry.path} projectId={projectId} entry={entry} readonly={archived} onGone={() => select(null)} /> : <EmptyState icon={<FolderOpen size={26} />} title={t("Pick a file")}>{t("Choose a file to see what it is for, its important symbols, and the tasks and decisions that relate to it.")}</EmptyState>}</div>
        </div>
      )}
      <Commits projectId={projectId} readonly={archived} />
    </div>
  );
}
