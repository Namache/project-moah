"""Reorganise shelves into the shared knowledge tree, in two steps.

    python scripts/refile-shelves.py dump records.json
        Writes every project's shelves and active records (IDs, titles, tags, shelves; never
        content) so a plan can be written from them.

    python scripts/refile-shelves.py apply plan.json report.md [--yes]
        Checks the plan, and with --yes carries it out: creates the shared tree, files the
        records on it, deletes the project shelves the plan names, and writes a report of what
        moved. Without --yes nothing is written. Records themselves are never changed.

The plan:
    {"tree": [{"path": "Knowledge > Game development", "keywords": [], "description": ""}],
     "file": {"trailhead": {"DEC-003": ["Knowledge > Game development > Game design"]}},
     "delete": {"trailhead": ["Auto", "Wind"]}}
A plan may also list records per shelf instead, naming a shelf by its path or its last name:
    {"shelves": {"Game design": {"trailhead": ["DEC-003"]}}}

Run it with the backend's Python environment while the app is closed, after a backup. The
database is the app's own unless PROJECT_BRAIN_DB_PATH names another.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import get_database_url
from app.db.migrate import upgrade_database
from app.db.session import make_engine, make_session_factory
from app.models.memory import Memory, MemoryTag
from app.models.project import GLOBAL_PROJECT_ID, Project
from app.models.task import Tag, Task, TaskTag
from app.schemas.graph import ShelfUpdate
from app.services.graph import Node
from app.services.shelves import ShelfService
from fastapi import HTTPException
from sqlalchemy import select

ACTOR = "refile-shelves"


def open_session():
    url = get_database_url()
    upgrade_database(url)
    return make_session_factory(make_engine(url))()


def projects(session) -> dict[str, Project]:
    rows = session.scalars(select(Project).where(Project.status != "archived"))
    return {p.slug or p.id: p for p in rows}


def project_for(session, ref: str) -> Project:
    if ref == GLOBAL_PROJECT_ID:
        return session.get(Project, GLOBAL_PROJECT_ID)
    found = session.scalar(
        select(Project).where((Project.slug == ref) | (Project.id == ref))
    )
    if found is None:
        raise SystemExit(f"No project {ref}")
    return found


def tag_names(session, project_id: str) -> dict[str, list[str]]:
    """Record id -> its tag names, for memory and tasks alike."""
    out: dict[str, list[str]] = defaultdict(list)
    for link, owner in ((MemoryTag, MemoryTag.memory_id), (TaskTag, TaskTag.task_id)):
        rows = session.execute(
            select(owner, Tag.name)
            .join(Tag, Tag.id == link.tag_id)
            .where(Tag.project_id == project_id)
        )
        for record_id, name in rows:
            out[record_id].append(name)
    return out


def dump(out: Path) -> None:
    session = open_session()
    service = ShelfService(session)
    data: dict = {}
    for key, project in projects(session).items():
        own = service._shelves(project.id)
        members = service.memberships(project.id)
        shared, shared_members = service.shared(project.id)
        on: dict[Node, list[str]] = defaultdict(list)
        for shelf in [*own, *shared]:
            for node in {**members, **shared_members}.get(shelf.id, ()):
                on[node].append(service.path(shelf))
        memories = session.scalars(
            select(Memory).where(
                Memory.project_id == project.id, Memory.status == "active"
            )
        )
        tasks = session.scalars(
            select(Task).where(Task.project_id == project.id, Task.status != "archived")
        )
        tags = tag_names(session, project.id)
        data[key] = {
            "name": project.name,
            "shelves": [
                {
                    "path": service.path(s),
                    "keywords": service._keywords(s),
                    "records": len(members.get(s.id, ())),
                }
                for s in own
            ],
            "records": [
                {
                    "id": m.human_id,
                    "type": m.type,
                    "title": m.title,
                    "tags": sorted(tags.get(m.id, [])),
                    "shelves": sorted(on.get(Node("memory", m.id), [])),
                }
                for m in memories
            ]
            + [
                {
                    "id": t.human_id,
                    "type": "task",
                    "title": t.title,
                    "status": t.status,
                    "tags": sorted(tags.get(t.id, [])),
                    "shelves": sorted(on.get(Node("task", t.id), [])),
                }
                for t in tasks
            ],
        }
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"Wrote {sum(len(p['records']) for p in data.values())} records to {out}")


def apply(plan_file: Path, report: Path, write: bool) -> None:
    plan = json.loads(plan_file.read_text())
    session = open_session()
    service = ShelfService(session)
    tree = {item["path"] for item in plan.get("tree", [])}
    by_name = {path.split(" > ")[-1]: path for path in tree}
    for shelf, projects_records in plan.get("shelves", {}).items():
        path = shelf if shelf in tree else by_name.get(shelf, shelf)
        for ref, records in projects_records.items():
            for record in records:
                plan.setdefault("file", {}).setdefault(ref, {}).setdefault(
                    record, []
                ).append(path)
    problems: list[str] = []
    filing: dict[tuple[str, str], list[str]] = defaultdict(
        list
    )  # (project, path) -> records
    for ref, records in plan.get("file", {}).items():
        project = project_for(session, ref)
        for record, paths in records.items():
            try:
                service.graph.resolve(project.id, record)
            except HTTPException:
                problems.append(f"{ref}: no record {record}")
                continue
            for path in paths:
                if path not in tree:
                    problems.append(
                        f"{ref}: {record} names {path}, which the tree lacks"
                    )
                else:
                    filing[(ref, path)].append(record)
    deleting: list[tuple[str, str]] = []
    for ref, names in plan.get("delete", {}).items():
        project = project_for(session, ref)
        for name in names:
            try:
                deleting.append((ref, service.path(service.get(project.id, name))))
            except HTTPException:
                problems.append(f"{ref}: no shelf {name} to delete")
    print(
        f"{len(tree)} shared shelves, {sum(len(r) for r in filing.values())} placements, "
        f"{len(deleting)} project shelves to delete, {len(problems)} problems"
    )
    for problem in problems:
        print("  " + problem)
    if not write:
        print("Nothing written. Run again with --yes to carry it out.")
        return
    for item in sorted(plan.get("tree", []), key=lambda i: i["path"].count(">")):
        shelf = service.ensure_path(
            GLOBAL_PROJECT_ID, item["path"], keywords=item.get("keywords"), actor=ACTOR
        )
        changes = {k: item[k] for k in ("keywords", "description") if item.get(k)}
        if changes:
            service.update(
                GLOBAL_PROJECT_ID, shelf.id, ShelfUpdate(**changes), actor=ACTOR
            )
    for (ref, path), records in sorted(filing.items()):
        project = project_for(session, ref)
        shelf = service.get(GLOBAL_PROJECT_ID, path)
        service.place(project.id, shelf.id, records, actor=ACTOR)
    for ref, path in deleting:
        service.delete(project_for(session, ref).id, path.split(" > ")[-1], actor=ACTOR)

    lines = ["# Shelves refiled", ""]
    for ref in sorted({r for r, _ in filing}):
        lines += [f"## {project_for(session, ref).name}", ""]
        for (r, path), records in sorted(filing.items()):
            if r == ref:
                lines.append(f"- {path}: {len(records)} ({', '.join(sorted(records))})")
        gone = [p for r, p in deleting if r == ref]
        if gone:
            lines += ["", f"Deleted project shelves: {', '.join(gone)}"]
        lines.append("")
    if problems:
        lines += ["## Skipped", "", *[f"- {p}" for p in problems], ""]
    report.write_text("\n".join(lines))
    print(f"Done. Report: {report}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "dump":
        dump(Path(args[1]))
    elif len(args) in (3, 4) and args[0] == "apply":
        apply(Path(args[1]), Path(args[2]), write=args[3:] == ["--yes"])
    else:
        print(__doc__)
        sys.exit(2)
