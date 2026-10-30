"""File knowledge, repository tree, and commit-to-task links. Metadata only, never source."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.checkpoint import Checkpoint
from app.models.files import (
    CommitFile,
    CommitTask,
    FileCheckpoint,
    FileMemory,
    FileSymbol,
    FileTask,
    GitCommit,
    ProjectFile,
)
from app.models.memory import Memory, MemoryTask
from app.models.task import Task
from app.schemas.files import (
    CheckpointRef,
    CommitList,
    CommitRead,
    CommitTaskRead,
    FileCreate,
    FileRead,
    FileTree,
    FileTreeEntry,
    FileUpdate,
    GitStatus,
    SymbolRead,
)
from app.schemas.memory import MemoryRef
from app.schemas.task import TaskRef
from app.services.activity import ActivityService
from app.services.checkpoints import CheckpointService
from app.services.errors import conflict, invalid, not_found
from app.services.git import (
    SHA_PATTERN,
    GitProblem,
    GitService,
    detect_language,
    normalize_repo_path,
)
from app.services.memory import MemoryService
from app.services.projects import ProjectService
from app.services.tasks import TaskService
from app.services.text import contains_pattern

TASK_ID_PATTERN = re.compile(r"\b([A-Za-z][A-Za-z0-9]{0,9})-(\d{1,6})\b")


class FileService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectService(session)
        self.tasks = TaskService(session)
        self.memory = MemoryService(session)
        self.checkpoints = CheckpointService(session)
        self.git = GitService(session)
        self.activity = ActivityService(session)

    # ---- lookup -----------------------------------------------------------------------

    def get(self, project_id: str, ref: str) -> ProjectFile:
        """By internal id, or by repository path."""
        matches = [ProjectFile.id == ref]
        try:
            matches.append(ProjectFile.path == normalize_repo_path(ref))
        except Exception:  # noqa: BLE001 - an invalid path is simply not a path
            pass
        found = self.session.scalar(
            select(ProjectFile).where(ProjectFile.project_id == project_id, or_(*matches))
        )
        if found is None:
            self.projects.get(project_id)
            raise not_found("No notes exist for that file in this project")
        return found

    def read(self, project_id: str, ref: str) -> FileRead:
        return self._reads(project_id, [self.get(project_id, ref)], check_stale=True)[0]

    def list(self, project_id: str, *, q: str | None = None, limit: int = 500) -> list[FileRead]:
        self.projects.get(project_id)
        statement = select(ProjectFile).where(ProjectFile.project_id == project_id)
        if q and q.strip():
            like = contains_pattern(q)
            statement = statement.where(
                func.casefold(ProjectFile.path).like(like, escape="\\")
                | func.casefold(func.coalesce(ProjectFile.purpose, "")).like(like, escape="\\")
            )
        rows = list(self.session.scalars(statement.order_by(ProjectFile.path).limit(limit)))
        return self._reads(project_id, rows, check_stale=False)

    # ---- writes -----------------------------------------------------------------------

    def create(self, project_id: str, payload: FileCreate) -> FileRead:
        project = self.projects.get(project_id)
        path = normalize_repo_path(payload.path)
        if self.session.scalar(
            select(ProjectFile.id).where(
                ProjectFile.project_id == project_id, ProjectFile.path == path
            )
        ):
            raise conflict("Notes for this file already exist")
        now = datetime.now(UTC)
        record = ProjectFile(
            project_id=project_id,
            path=path,
            language=payload.language or detect_language(path),
            purpose=payload.purpose,
            summary=payload.summary,
            last_seen_hash=self.git.file_hash(project, path),
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)
        self.session.flush()
        self._set_symbols(record, payload.symbols)
        links = self._set_links(
            record, payload.task_ids, payload.memory_ids, payload.checkpoint_ids
        )
        self._record(record, "FILE_CREATED")
        if links:
            self._record(record, "FILE_ASSOCIATED")
        self.session.commit()
        return self.read(project_id, record.id)

    def update(self, project_id: str, ref: str, payload: FileUpdate) -> FileRead:
        record = self.get(project_id, ref)
        changes = payload.model_dump(exclude_unset=True)
        symbols = payload.symbols if "symbols" in changes else None
        for field in ("language", "purpose", "summary"):
            if field in changes:
                setattr(record, field, changes[field])
        if symbols is not None:
            self._set_symbols(record, symbols)
        linked = self._set_links(
            record,
            changes.get("task_ids"),
            changes.get("memory_ids"),
            changes.get("checkpoint_ids"),
        )
        record.updated_at = datetime.now(UTC)
        self._record(record, "FILE_ASSOCIATED" if linked else "FILE_UPDATED")
        self.session.commit()
        return self.read(project_id, record.id)

    def mark_reviewed(self, project_id: str, ref: str) -> FileRead:
        """Remember the file's current content as the version these notes describe."""
        record = self.get(project_id, ref)
        current = self.git.file_hash(self.projects.get(project_id), record.path)
        if current is None:
            raise conflict("The file could not be read, so it cannot be marked as reviewed")
        record.last_seen_hash = current
        record.updated_at = datetime.now(UTC)
        self._record(record, "FILE_UPDATED")
        self.session.commit()
        return self.read(project_id, record.id)

    def delete(self, project_id: str, ref: str) -> None:
        """Remove Project Moah's notes about a file. The file itself is never touched."""
        record = self.get(project_id, ref)
        self.session.delete(record)
        self.session.commit()

    # ---- tree and git ------------------------------------------------------------------

    def tree(self, project_id: str) -> FileTree:
        project = self.projects.get(project_id)
        git = self.git.status(project)
        notes = {
            f.path: f
            for f in self.session.scalars(
                select(ProjectFile).where(ProjectFile.project_id == project_id)
            )
        }
        changed = {c.path: c.status for c in git.changed}
        try:
            paths, source, truncated = self.git.list_paths(project)
        except GitProblem as problem:
            if git.state == "ok":
                git = GitStatus(state=problem.state, message=str(problem))
            paths, source, truncated = [], "notes", False
        entries = {p: FileTreeEntry(path=p, changed=changed.get(p)) for p in paths}
        for path, record in notes.items():
            entry = entries.setdefault(path, FileTreeEntry(path=path))
            entry.file_id, entry.has_notes = record.id, True
            if record.last_seen_hash:
                current = self.git.file_hash(project, path)
                entry.stale = None if current is None else current != record.last_seen_hash
        return FileTree(
            git=git,
            entries=sorted(entries.values(), key=lambda e: e.path),
            truncated=truncated,
            source=source,
        )

    def file_history(self, project_id: str, ref: str, limit: int = 8) -> CommitList:
        project = self.projects.get(project_id)
        record = self.get(project_id, ref)
        git = self.git.status(project)
        if git.state != "ok":
            return CommitList(git=git, commits=[])
        raw = self.git.recent_commits(project, limit, path=record.path)
        return CommitList(git=git, commits=[self._commit_read(project_id, c, set()) for c in raw])

    def commits(self, project_id: str, *, limit: int = 25, task: str | None = None) -> CommitList:
        project = self.projects.get(project_id)
        git = self.git.status(project)
        live: list[dict] = []
        if git.state == "ok":
            try:
                live = self.git.recent_commits(project, limit)
            except GitProblem as problem:
                git = GitStatus(state=problem.state, message=str(problem), root_path=git.root_path)
        task_id = self.tasks.get(project_id, task).id if task else None
        stored = self._stored_commits(project_id, task_id)
        seen = {c["sha"] for c in live}
        known = {c.sha for c in stored}
        if task_id:  # for one task, show only commits confirmed for it
            live = [c for c in live if c["sha"] in known]
        reads = [self._commit_read(project_id, c, seen) for c in live]
        for commit in stored:
            if commit.sha not in seen:
                reads.append(
                    self._commit_read(project_id, self._commit_dict(commit), set(), kept=True)
                )
        return CommitList(git=git, commits=reads)

    def link_commit(
        self, project_id: str, sha: str, task_ref: str, *, origin: str = "human"
    ) -> CommitRead:
        project = self.projects.get(project_id)
        task = self.tasks.get(project_id, task_ref)
        existing = self._stored_commit(project_id, sha)
        if existing is None:
            try:
                meta = self.git.commit(project, sha)
            except GitProblem as problem:
                raise conflict(f"{problem} The commit could not be read.") from problem
            existing = GitCommit(
                project_id=project_id,
                sha=meta["sha"],
                subject=meta["subject"],
                author=meta["author"],
                committed_at=meta["committed_at"],
                created_at=datetime.now(UTC),
            )
            self.session.add(existing)
            self.session.flush()
            for path in meta["files"]:
                self.session.add(
                    CommitFile(commit_id=existing.id, path=path, project_id=project_id)
                )
            self.activity.record(
                project_id,
                "GIT_COMMIT_DETECTED",
                entity_type="commit",
                entity_id=existing.id,
                metadata={"sha": existing.sha[:10], "title": existing.subject},
            )
        link = self.session.get(CommitTask, (existing.id, task.id))
        if link is None:
            self.session.add(
                CommitTask(
                    commit_id=existing.id,
                    task_id=task.id,
                    project_id=project_id,
                    status="confirmed",
                    origin=origin,
                    created_at=datetime.now(UTC),
                )
            )
        else:
            link.status = "confirmed"
        self.activity.record(
            project_id,
            "COMMIT_LINKED",
            entity_type="commit",
            entity_id=existing.id,
            task_id=task.id,
            metadata={"sha": existing.sha[:10], "task": task.human_id},
        )
        self.session.commit()
        return self._commit_read(project_id, self._commit_dict(existing), {existing.sha})

    def unlink_commit(self, project_id: str, sha: str, task_ref: str) -> None:
        task = self.tasks.get(project_id, task_ref)
        commit = self._stored_commit(project_id, sha)
        link = self.session.get(CommitTask, (commit.id, task.id)) if commit else None
        if link is None:
            raise not_found("That commit is not linked to this task")
        self.session.delete(link)
        self.session.commit()

    def _stored_commit(self, project_id: str, sha: str) -> GitCommit | None:
        """The one stored commit a full or abbreviated SHA names, or None."""
        if not SHA_PATTERN.fullmatch(sha):
            raise invalid("That is not a commit SHA.")
        found = list(
            self.session.scalars(
                select(GitCommit)
                .where(GitCommit.project_id == project_id, GitCommit.sha.startswith(sha.lower()))
                .limit(2)
            )
        )
        if len(found) > 1:
            raise conflict("That short SHA matches more than one commit. Use more characters.")
        return found[0] if found else None

    # ---- context support ---------------------------------------------------------------

    def files_for_task(
        self, project_id: str, task_id: str, limit: int = 12
    ) -> list[tuple[ProjectFile, str]]:
        """Files linked to a task directly, or through memory linked to it, with the reason."""
        direct = {
            f.id: (f, "linked to this task")
            for f in self.session.scalars(
                select(ProjectFile)
                .join(FileTask, FileTask.file_id == ProjectFile.id)
                .where(ProjectFile.project_id == project_id, FileTask.task_id == task_id)
            )
        }
        via_memory = self.session.scalars(
            select(ProjectFile)
            .join(FileMemory, FileMemory.file_id == ProjectFile.id)
            .join(Memory, Memory.id == FileMemory.memory_id)
            .join(MemoryTask, MemoryTask.memory_id == Memory.id)
            .where(
                ProjectFile.project_id == project_id,
                MemoryTask.task_id == task_id,
                Memory.status == "active",
                Memory.ai_visibility != "hidden",
            )
            .order_by(ProjectFile.path)
        )
        extra = [f for f in via_memory if f.id not in direct]
        return (list(direct.values()) + [(f, "linked to related memory") for f in extra])[:limit]

    def changed_paths(self, project_id: str) -> set[str]:
        status = self.git.status(self.projects.get(project_id))
        return {c.path for c in status.changed} if status.state == "ok" else set()

    # ---- internals ---------------------------------------------------------------------

    def _record(self, record: ProjectFile, event: str) -> None:
        self.activity.record(
            record.project_id,
            event,
            entity_type="file",
            entity_id=record.id,
            metadata={"title": record.path},
        )

    def _set_symbols(self, record: ProjectFile, symbols: list) -> None:
        for old in self.session.scalars(select(FileSymbol).where(FileSymbol.file_id == record.id)):
            self.session.delete(old)
        self.session.flush()
        seen: set[tuple[str, str]] = set()
        for symbol in symbols:
            key = (symbol.name, symbol.kind)
            if key in seen:
                continue
            seen.add(key)
            self.session.add(
                FileSymbol(
                    file_id=record.id, name=symbol.name, kind=symbol.kind, summary=symbol.summary
                )
            )

    def _set_links(
        self,
        record: ProjectFile,
        task_refs: list[str] | None,
        memory_refs: list[str] | None,
        checkpoint_refs: list[str] | None,
    ) -> bool:
        pid, changed = record.project_id, False
        wanted = {
            FileTask: (
                "task_id",
                None if task_refs is None else {self.tasks.get(pid, r).id for r in task_refs},
            ),
            FileMemory: (
                "memory_id",
                None if memory_refs is None else {self.memory.get(pid, r).id for r in memory_refs},
            ),
            FileCheckpoint: (
                "checkpoint_id",
                None
                if checkpoint_refs is None
                else {self.checkpoints.get(pid, r).id for r in checkpoint_refs},
            ),
        }
        for model, (column, ids) in wanted.items():
            if ids is None:
                continue
            current = {
                getattr(row, column): row
                for row in self.session.scalars(select(model).where(model.file_id == record.id))
            }
            for key, link in current.items():
                if key not in ids:
                    self.session.delete(link)
                    changed = True
            for key in ids - current.keys():
                self.session.add(model(file_id=record.id, project_id=pid, **{column: key}))
                changed = True
        return changed

    def _reads(
        self, project_id: str, files: list[ProjectFile], *, check_stale: bool
    ) -> list[FileRead]:
        if not files:
            return []
        ids = [f.id for f in files]
        symbols: dict[str, list[SymbolRead]] = defaultdict(list)
        for s in self.session.scalars(
            select(FileSymbol).where(FileSymbol.file_id.in_(ids)).order_by(FileSymbol.name)
        ):
            symbols[s.file_id].append(SymbolRead.model_validate(s))
        tasks: dict[str, list[TaskRef]] = defaultdict(list)
        for fid, task in self.session.execute(
            select(FileTask.file_id, Task)
            .join(Task, Task.id == FileTask.task_id)
            .where(FileTask.file_id.in_(ids))
            .order_by(Task.human_id)
        ):
            tasks[fid].append(TaskRef.model_validate(task))
        memories: dict[str, list[MemoryRef]] = defaultdict(list)
        for fid, memory in self.session.execute(
            select(FileMemory.file_id, Memory)
            .join(Memory, Memory.id == FileMemory.memory_id)
            .where(FileMemory.file_id.in_(ids))
            .order_by(Memory.human_id)
        ):
            memories[fid].append(MemoryRef.model_validate(memory))
        checkpoints: dict[str, list[CheckpointRef]] = defaultdict(list)
        for fid, cp in self.session.execute(
            select(FileCheckpoint.file_id, Checkpoint)
            .join(Checkpoint, Checkpoint.id == FileCheckpoint.checkpoint_id)
            .where(FileCheckpoint.file_id.in_(ids))
            .order_by(Checkpoint.created_at.desc())
        ):
            checkpoints[fid].append(CheckpointRef(id=cp.id, title=cp.title))
        project = self.projects.get(project_id) if check_stale else None
        reads = []
        for f in files:
            read = FileRead.model_validate(f, from_attributes=True)
            read.symbols, read.tasks = symbols.get(f.id, []), tasks.get(f.id, [])
            read.memories, read.checkpoints = memories.get(f.id, []), checkpoints.get(f.id, [])
            if project is not None and f.last_seen_hash:
                current = self.git.file_hash(project, f.path)
                read.stale = None if current is None else current != f.last_seen_hash
            reads.append(read)
        return reads

    def _stored_commits(self, project_id: str, task_id: str | None) -> list[GitCommit]:
        statement = select(GitCommit).where(GitCommit.project_id == project_id)
        if task_id:
            statement = statement.where(
                GitCommit.id.in_(select(CommitTask.commit_id).where(CommitTask.task_id == task_id))
            )
        else:
            statement = statement.where(GitCommit.id.in_(select(CommitTask.commit_id)))
        return list(self.session.scalars(statement.order_by(GitCommit.committed_at.desc())))

    @staticmethod
    def _commit_dict(commit: GitCommit) -> dict:
        return {
            "sha": commit.sha,
            "subject": commit.subject,
            "author": commit.author,
            "committed_at": commit.committed_at,
            "files": [],
        }

    def _commit_read(
        self, project_id: str, c: dict, live: set[str], *, kept: bool = False
    ) -> CommitRead:
        stored = self.session.scalar(
            select(GitCommit).where(GitCommit.project_id == project_id, GitCommit.sha == c["sha"])
        )
        files = c.get("files") or []
        tasks: list[CommitTaskRead] = []
        confirmed: set[str] = set()
        if stored is not None:
            files = files or list(
                self.session.scalars(
                    select(CommitFile.path)
                    .where(CommitFile.commit_id == stored.id)
                    .order_by(CommitFile.path)
                )
            )
            for link, task in self.session.execute(
                select(CommitTask, Task)
                .join(Task, Task.id == CommitTask.task_id)
                .where(CommitTask.commit_id == stored.id)
            ):
                confirmed.add(task.id)
                tasks.append(
                    CommitTaskRead(
                        task=TaskRef.model_validate(task), status=link.status, origin=link.origin
                    )
                )
        # Suggestions come from task IDs written in the message. They are shown, never stored.
        for prefix, number in TASK_ID_PATTERN.findall(c["subject"]):
            try:
                task = self.tasks.get(project_id, f"{prefix}-{number}")
            except Exception:  # noqa: BLE001 - not a task of this project
                continue
            if task.id not in confirmed and all(t.task.id != task.id for t in tasks):
                tasks.append(
                    CommitTaskRead(
                        task=TaskRef.model_validate(task),
                        status="suggested",
                        origin="commit message",
                    )
                )
        return CommitRead(
            sha=c["sha"],
            short_sha=c["sha"][:8],
            subject=c["subject"],
            author=c["author"],
            committed_at=c["committed_at"],
            files=files,
            tasks=tasks,
            in_repository=not kept,
        )
