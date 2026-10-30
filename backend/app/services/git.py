"""Read-only Git awareness for one project's repository.

Only fixed, read-only Git commands run, always through an argument list (never a shell),
always against that project's own ``root_path``, and with prompts and optional locks off.
Nothing here can change history, the index, or the working tree. Every failure becomes a
``GitStatus`` with a plain message so the rest of the app keeps working.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.schemas.files import ChangedFile, GitStatus
from app.services.errors import invalid

TIMEOUT_SECONDS = 10
MAX_CHANGED = 500
MAX_TREE = 20000
MAX_HASH_BYTES = 5_000_000
SHA_PATTERN = re.compile(r"[0-9a-fA-F]{7,64}")
SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".next",
    "target",
    ".idea",
    ".vscode",
    ".godot",
    ".import",
}
STATUS_LABELS = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "?": "untracked",
    "U": "conflicted",
    "T": "modified",
}


def in_sandbox() -> bool:
    """True inside a Flatpak, where only folders the person shares are visible."""
    return Path("/.flatpak-info").exists()


MESSAGES = {
    "not_shared": (
        "Project Moah runs in a sandbox and can only see folders you share with it, so it "
        "cannot see this one. Choose the folder again with Choose folder in the project "
        "settings, or share it read-only (see Help)."
    ),
    "no_path": "This project has no repository folder yet. Add one in the project settings.",
    "path_missing": "The repository folder could not be found. It may have moved.",
    "git_missing": "Git is not available to Project Moah, so repository details can't be shown.",
    "not_repo": "This folder is not a Git repository.",
    "unsafe_repo": "Git refused to open this repository because of its folder ownership.",
    "timeout": "Git took too long to answer.",
    "error": "Git could not read this repository.",
}


class GitProblem(Exception):
    def __init__(self, state: str, detail: str = "") -> None:
        super().__init__(detail or MESSAGES.get(state, state))
        self.state = state


def normalize_repo_path(raw: str) -> str:
    """A safe POSIX path relative to a repository root, or a 422 error."""
    if "\x00" in raw or "\\" in raw:
        raise invalid("File paths cannot contain backslashes or null characters")
    path = raw.strip().removeprefix("./")
    if not path or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise invalid("File paths must be relative to the repository, such as src/main.py")
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise invalid("File paths cannot leave the repository")
    return "/".join(parts)


def detect_language(path: str) -> str | None:
    names = {"dockerfile": "docker", "makefile": "make"}
    name = path.rsplit("/", 1)[-1].lower()
    if name in names:
        return names[name]
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    return {
        "py": "python",
        "ts": "typescript",
        "tsx": "typescript",
        "js": "javascript",
        "jsx": "javascript",
        "cjs": "javascript",
        "mjs": "javascript",
        "gd": "gdscript",
        "cs": "csharp",
        "rs": "rust",
        "go": "go",
        "java": "java",
        "kt": "kotlin",
        "c": "c",
        "h": "c",
        "cpp": "cpp",
        "hpp": "cpp",
        "rb": "ruby",
        "php": "php",
        "swift": "swift",
        "md": "markdown",
        "json": "json",
        "yml": "yaml",
        "yaml": "yaml",
        "toml": "toml",
        "html": "html",
        "css": "css",
        "sql": "sql",
        "sh": "shell",
        "tscn": "godot-scene",
        "tres": "godot-resource",
        "gdshader": "shader",
    }.get(ext)


class GitService:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ---- repository access ------------------------------------------------------------

    @staticmethod
    def _root(project: Project) -> Path:
        if not project.root_path:
            raise GitProblem("no_path")
        root = Path(project.root_path)
        try:
            if not root.is_dir():
                # In a sandbox a folder is usually "missing" because it was never shared.
                raise GitProblem("not_shared" if in_sandbox() else "path_missing")
        except OSError as exc:
            raise GitProblem("path_missing") from exc
        return root

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        git = shutil.which("git")
        if git is None:
            raise GitProblem("git_missing")
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/nonexistent"),
            "LC_ALL": "C",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
        }
        try:
            done = subprocess.run(  # noqa: S603 - fixed argument list, no shell
                [git, "--no-pager", "-c", "core.quotepath=off", "-C", str(root), *args],
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitProblem("timeout") from exc
        except OSError as exc:
            raise GitProblem("git_missing") from exc
        if done.returncode != 0:
            err = done.stderr.decode("utf-8", "replace").lower()
            if "dubious ownership" in err or "safe.directory" in err:
                raise GitProblem("unsafe_repo")
            if "not a git repository" in err:
                raise GitProblem("not_repo")
            raise GitProblem("error", err.strip()[:200])
        return done.stdout.decode("utf-8", "replace")

    def _other_projects_sharing_root(self, project: Project) -> list[str]:
        if not project.root_path:
            return []
        rows = self.session.scalars(
            select(Project.name).where(
                Project.root_path == project.root_path, Project.id != project.id
            )
        )
        return list(rows)

    # ---- status -----------------------------------------------------------------------

    def status(self, project: Project) -> GitStatus:
        try:
            root = self._root(project)
            self._git(root, "rev-parse", "--show-toplevel")
            # The project may be a subfolder of the repository: Git reports paths from the
            # repository root, while the project's files are relative to its own folder.
            prefix = self._git(root, "rev-parse", "--show-prefix").strip()
            has_head = self._has_head(root)
            branch = (
                self._git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
                if has_head
                else self._git(root, "symbolic-ref", "--short", "HEAD").strip()
            )
            head = subject = None
            if has_head:
                head = self._git(root, "rev-parse", "HEAD").strip()
                subject = self._git(root, "log", "-1", "--pretty=format:%s").strip()
            raw = self._git(
                root, "status", "--porcelain=v1", "-z", "--untracked-files=normal", "--", "."
            )
        except GitProblem as problem:
            return GitStatus(
                state=problem.state,
                message=str(problem),
                root_path=project.root_path,
                warnings=self._warnings(project),
            )
        changed = self._parse_status(raw, prefix)
        return GitStatus(
            state="ok",
            message="Repository is available.",
            root_path=str(root),
            branch=None if branch == "HEAD" else branch,
            detached=branch == "HEAD",
            head=head,
            head_subject=subject,
            clean=not changed,
            changed=changed[:MAX_CHANGED],
            changed_total=len(changed),
            warnings=self._warnings(project),
        )

    def _warnings(self, project: Project) -> list[str]:
        others = self._other_projects_sharing_root(project)
        if others:
            return [f"The same repository folder is also used by: {', '.join(sorted(others))}."]
        return []

    def _has_head(self, root: Path) -> bool:
        try:
            self._git(root, "rev-parse", "--verify", "-q", "HEAD")
            return True
        except GitProblem:
            return False

    @staticmethod
    def _parse_status(raw: str, prefix: str = "") -> list[ChangedFile]:
        entries = raw.split("\x00")
        changed: list[ChangedFile] = []
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if len(entry) < 4:
                continue
            code, path = entry[:2], entry[3:]
            if "R" in code or "C" in code:
                index += 1  # the original name follows a rename or copy (staged or not)
            if prefix and path.startswith(prefix):
                path = path[len(prefix) :]
            letter = "?" if code == "??" else next((c for c in code if c not in " "), "M")
            if "U" in code or code in ("AA", "DD"):
                letter = "U"
            changed.append(ChangedFile(path=path, status=STATUS_LABELS.get(letter, "modified")))
        return changed

    # ---- commits ----------------------------------------------------------------------

    def recent_commits(
        self, project: Project, limit: int = 25, path: str | None = None
    ) -> list[dict]:
        root = self._root(project)
        if not self._has_head(root):
            return []
        args = ["log", f"-n{int(limit)}", "--pretty=format:%H%x1f%an%x1f%aI%x1f%s%x1e"]
        if path:
            args += ["--", normalize_repo_path(path)]
        return [
            self._parse_commit(chunk)
            for chunk in self._git(root, *args).split("\x1e")
            if chunk.strip()
        ]

    def commit(self, project: Project, sha: str) -> dict:
        """Metadata and touched files for one commit, or a GitProblem."""
        if not SHA_PATTERN.fullmatch(sha):
            raise invalid("A commit ID is 7 to 40 hexadecimal characters")
        root = self._root(project)
        text = self._git(
            root, "show", "-s", "--pretty=format:%H%x1f%an%x1f%aI%x1f%s", f"{sha}^{{commit}}"
        )
        commit = self._parse_commit(text)
        names = self._git(
            root, "show", "--name-only", "--pretty=format:", "--no-renames", f"{sha}^{{commit}}"
        )
        commit["files"] = [n for n in names.splitlines() if n.strip()][:200]
        return commit

    @staticmethod
    def _parse_commit(chunk: str) -> dict:
        sha, author, when, subject = (chunk.strip("\n").split("\x1f") + ["", "", "", ""])[:4]
        try:
            committed = datetime.fromisoformat(when)
        except ValueError:
            committed = None
        return {
            "sha": sha.strip(),
            "author": author or None,
            "committed_at": committed,
            "subject": subject,
            "files": [],
        }

    # ---- files ------------------------------------------------------------------------

    def list_paths(self, project: Project) -> tuple[list[str], str, bool]:
        """Repository file paths, where they came from, and whether the list was capped."""
        root = self._root(project)
        try:
            raw = self._git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
            paths = sorted({p for p in raw.split("\x00") if p})
            source = "git"
        except GitProblem as problem:
            if problem.state not in ("git_missing", "not_repo"):
                raise
            paths, source = self._walk(root), "folder"
        return paths[:MAX_TREE], source, len(paths) > MAX_TREE

    @staticmethod
    def _walk(root: Path) -> list[str]:
        found: list[str] = []
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            base = Path(current)
            for name in sorted(files):
                if name.startswith(".") and name not in (".gitignore", ".env.example"):
                    continue
                found.append((base / name).relative_to(root).as_posix())
                if len(found) > MAX_TREE:
                    return found
        return found

    def file_hash(self, project: Project, path: str) -> str | None:
        """SHA-256 of a file's current bytes, or None if it cannot be read safely."""
        try:
            root = self._root(project).resolve()
            target = (root / normalize_repo_path(path)).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                return None
            if target.stat().st_size > MAX_HASH_BYTES:
                return None
            return hashlib.sha256(target.read_bytes()).hexdigest()
        except (GitProblem, OSError):
            return None
