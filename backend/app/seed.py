"""Idempotent opt-in demo seed: three projects with milestones, tasks, and focus."""

from app.core.config import get_database_url
from app.db.migrate import upgrade_database
from app.db.session import make_engine, make_session_factory
from app.schemas.memory import MemoryCreate
from app.schemas.project import ProjectCreate
from app.schemas.task import CriterionUpdate, MilestoneCreate, RelationshipCreate, TaskCreate
from app.services.memory import MemoryService
from app.services.milestones import MilestoneService
from app.services.projects import ProjectService, name_key
from app.services.tasks import TaskService

SEED_PROJECTS = (
    ProjectCreate(
        name="Trailhead",
        description="A home for the Trailhead game project.",
        icon="⛰️",
        accent="#D99A53",
    ),
    ProjectCreate(
        name="Starling",
        description="A home for the Starling game project.",
        icon="✦",
        accent="#A88BE4",
    ),
    ProjectCreate(
        name="Greenline",
        description="A home for the Greenline project.",
        icon="🌿",
        accent="#62BEA2",
    ),
)


def seed_projects(database_url: str | None = None) -> int:
    resolved_url = database_url or get_database_url()
    upgrade_database(resolved_url)
    engine = make_engine(resolved_url)
    created = 0
    try:
        with make_session_factory(engine)() as session:
            service = ProjectService(session)
            for payload in SEED_PROJECTS:
                if service.projects.get_by_name_key(name_key(payload.name)) is None:
                    service.create(payload)
                    created += 1
            seed_tasks(session)
            seed_memory(session)
    finally:
        engine.dispose()
    return created


# project -> (milestone, [(prefix, title, criteria with done flags, next action, focus)])
SEED_TASKS = {
    "Trailhead": (
        "Demo 0.1.1",
        [
            ("SAVE", "Save Schema Migration", [], "Add a version field to save files.", False),
            (
                "CAMP",
                "Camp Population Capacity",
                [
                    ("Track camp capacity", True),
                    ("Block recruitment when full", True),
                    ("Show warning", True),
                    ("Expansion increases capacity", True),
                    ("Migrate old saves", False),
                ],
                "Implement migration fallback for old saves.",
                True,
            ),
        ],
    ),
    "Starling": (
        "Prototype",
        [("CBT", "Turn Order System", [], "Sort combatants by speed each round.", True)],
    ),
    "Greenline": ("Version 1.4", [("TTS", "Read-Aloud Settings", [], None, False)]),
}


def seed_tasks(session) -> None:
    """Add demo tasks to a seeded project only while it has none."""
    projects = ProjectService(session)
    tasks = TaskService(session)
    for project_name, (milestone_name, items) in SEED_TASKS.items():
        project = projects.projects.get_by_name_key(name_key(project_name))
        if project is None or tasks.list(project.id, include_archived=True):
            continue
        milestone = MilestoneService(session).create(
            project.id, MilestoneCreate(name=milestone_name, status="active")
        )
        created = []
        for prefix, title, criteria, next_action, focus in items:
            task = tasks.create(
                project.id,
                TaskCreate(
                    title=title,
                    prefix=prefix,
                    milestone_id=milestone.id,
                    next_action=next_action,
                    acceptance_criteria=[text for text, _ in criteria],
                ),
            )
            for criterion, (_, done) in zip(task.acceptance_criteria, criteria, strict=True):
                if done:
                    tasks.update_criterion(
                        project.id, task.id, criterion.id, CriterionUpdate(is_completed=True)
                    )
            if focus:
                tasks.start_work(project.id, task.id)
            created.append(task)
        if project_name == "Trailhead":
            tasks.add_relationship(
                project.id,
                created[1].id,
                RelationshipCreate(type="depends_on", target=created[0].human_id),
            )


# project -> [(type, title, content, locked, importance)]
SEED_MEMORY = {
    "Trailhead": [
        (
            "decision",
            "Starting capacity is 6",
            "A new camp starts with room for 6 Folk.",
            True,
            "high",
        ),
        (
            "rule",
            "Save migrations must preserve older saves",
            "Never drop fields without a fallback.",
            False,
            "high",
        ),
        (
            "bug",
            "Old saves contain no camp_capacity",
            "Saves made before v0.1.1 load capacity as zero.",
            False,
            "high",
        ),
        (
            "idea",
            "Tents could raise capacity temporarily",
            "Only an idea. Not a requirement.",
            False,
            "low",
        ),
    ],
    "Starling": [("decision", "Maximum party size is 4", "Applies to every battle.", True, "high")],
}


def seed_memory(session) -> None:
    """Add demo memory to a seeded project only while it has none."""
    projects = ProjectService(session)
    memory = MemoryService(session)
    for project_name, items in SEED_MEMORY.items():
        project = projects.projects.get_by_name_key(name_key(project_name))
        if project is None or memory.list(project.id, statuses=["active", "archived"]):
            continue
        for memory_type, title, content, is_locked, importance in items:
            memory.create(
                project.id,
                MemoryCreate(
                    type=memory_type,
                    title=title,
                    content=content,
                    is_locked=is_locked,
                    importance=importance,
                    ai_visibility="manual_only" if memory_type == "idea" else "relevant_only",
                ),
            )


if __name__ == "__main__":
    count = seed_projects()
    print(f"Seeded {count} project(s).")
