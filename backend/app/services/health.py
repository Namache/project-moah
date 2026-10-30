"""Brain health, knowledge clusters and shelf suggestions (Link System Phase 3).

- Health (design sections 49 and 50): how big and how well connected the graph is, how much
  of it is weak, orphaned or in conflict, and how retrieval has gone: depth, pack size, how
  often agents gave feedback and how often what they got helped. Per shelf, how connected its
  records are among themselves.
- Clusters (section 26): groups of records that link to each other more than to the rest,
  found by weighted label propagation over the active links. Deterministic: the same graph
  always gives the same clusters. A cluster is named after the word its titles share that is
  most typical of it compared with the whole project.
- Shelf suggestions (sections 51, 54 and 55): a cluster no shelf covers becomes a suggested
  shelf; a cluster inside a large shelf becomes a suggested sub-shelf; two shelves holding
  mostly the same records are suggested for merging. Nothing changes until a person accepts.
  Shelves are views, so accepting never touches a record or a link.

Phase 4 (brain expansion and self-tuning shelves, design sections 25, 51 and 54):
- a record that links mostly to one shelf's members but is not on it: add it;
- a word typical of a shelf's members that the shelf does not listen for: add it as a keyword;
- a member agents keep calling noise and never useful: take it off the shelf;
- three or more bugs and warnings in one cluster: a recurring failure area (a notice only);
- the same lesson written in two projects: share it, as one Global record both projects route to.
Again nothing changes until a person accepts.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting
from app.models.checkpoint import Checkpoint
from app.models.graph import NodeUsefulness, RetrievalSession, Shelf, ShelfMember
from app.models.memory import Memory
from app.models.project import GLOBAL_PROJECT_ID, Project, utc_now
from app.schemas.memory import HUMAN, MemoryCreate
from app.services.discovery import DiscoveryService, in_every_pack
from app.services.errors import invalid, not_found
from app.services.graph import GraphService, Node
from app.services.search import STOPWORDS
from app.services.shelves import WORD_EVIDENCE, ShelfService
from app.services.text import name_key
from app.services.upkeep import DECAY_SETTING, _aware

STRONG_FROM = 0.7
CLUSTER_MIN = 4  # smaller groups are just a few linked records
SUGGEST_MIN = 5  # clusters this big are worth a shelf
NAME_SHARE = 0.35  # the naming word must appear in at least this share of the cluster's titles
COVERED = 0.5  # a cluster with this share of its records on one shelf is already organised
SPLIT_FROM = 12  # a shelf this big may grow sub-shelves
SPLIT_INSIDE = 0.8  # share of a cluster on the shelf to count as inside it
SPLIT_MAX = 0.7  # a "sub-shelf" holding more than this share of its parent is the parent
MERGE_FROM = 0.6  # Jaccard overlap of two shelves' records
SUGGEST_MAX = 30  # bigger clusters are a hub (an epic, a milestone), not a topic
SUGGESTIONS_SHOWN = 5  # per project, biggest first
NAME_COMMON = 0.2  # a word in this share of the other titles names nothing
DISMISSED = "dismissed_shelf_suggestions"
CLUSTER_SNAPSHOT = "cluster_snapshot"  # yesterday's clusters, so new and growing ones show
WORD = re.compile(r"[a-z][a-z']{3,}")
# Phase 4 suggestion thresholds
ADD_MEMBER_LINKS = 2  # strong links into a shelf's members...
ADD_MEMBER_SHARE = 0.6  # ...making up this share of the record's links
ADD_MEMBER_STRENGTH = 0.5
KEYWORD_MEMBERS = 4  # a shelf needs this many members before it learns keywords
KEYWORD_SHARE = 0.5  # a word in this share of member titles...
NOISE_VERDICTS = 3  # "not useful" this often, and never useful, takes a member off
PATTERN_ISSUES = 3  # bugs and warnings in one cluster that make a recurring failure area
SHARE_WORDS = 3  # the same lesson in two projects: titles sharing this many words...
SHARE_OF = 0.6  # ...making up this share of the shorter title
SHARE_TYPES = ("rule", "warning", "fact", "decision")
PER_KIND = 3  # Phase 4 suggestions shown per kind and project
RECENT = timedelta(days=30)  # "lately", for how much agents use the brain
RECORDS_SHOWN = 8  # records listed under a suggestion, so a person sees what it would touch
# What the brain tidies on its own each day; merges and new categories need a name or a person.
AUTO_KINDS = ("place", "add_member", "add_keyword", "remove_member")
LEARN_SESSIONS = 3  # a word that found a shelf's records in this many packs becomes a keyword
ORGANIZER = "moah"
# Status words people put in titles ("RESOLVED: ...") say how a record stands, not what it is
# about; a few filler words say nothing either.
STATUS_WORDS = {
    "based",
    "using",
    "make",
    "need",
    "keep",
    "work",
    "resolved",
    "approved",
    "done",
    "fixed",
    "pending",
    "rejected",
    "todo",
    "draft",
    "final",
    "update",
    "updated",
    "added",
    "implement",
    "implemented",
    "wip",
    "open",
    "closed",
    "known",
    "owner",
    "user",
    "merged",
    "investigate",
    "never",
    "always",
}


def _words(title: str) -> set[str]:
    return {
        w for w in WORD.findall(title.casefold()) if w not in STOPWORDS and w not in STATUS_WORDS
    }


def find_clusters(nodes: list[dict], links: list[dict]) -> list[list[str]]:
    """Node keys grouped by weighted label propagation over non-candidate links."""
    neighbours: dict[str, dict[str, float]] = {n["key"]: {} for n in nodes}
    for link in links:
        a, b = link["source"], link["target"]
        if link["status"] == "candidate" or a not in neighbours or b not in neighbours:
            continue
        w = float(link["strength"])
        neighbours[a][b] = neighbours[a].get(b, 0.0) + w
        neighbours[b][a] = neighbours[b].get(a, 0.0) + w
    order = sorted(k for k, v in neighbours.items() if v)
    label = {k: k for k in order}
    for _ in range(20):
        changed = False
        for key in order:
            votes: dict[str, float] = {}
            for other, w in neighbours[key].items():
                votes[label[other]] = votes.get(label[other], 0.0) + w
            best = max(votes.items(), key=lambda kv: (kv[1], [-ord(c) for c in kv[0]]))[0]
            if best != label[key] and votes[best] > votes.get(label[key], 0.0):
                label[key] = best
                changed = True
        if not changed:
            break
    # Label propagation can cut a tight group in two (a ring of five becomes three and two).
    # Two groups that link to each other at least as much as the smaller one links inside
    # are one group.
    while True:
        inside: dict[str, float] = {}
        between: dict[tuple[str, str], float] = {}
        for a in order:
            for b, w in neighbours[a].items():
                if a < b:
                    la, lb = label[a], label[b]
                    if la == lb:
                        inside[la] = inside.get(la, 0.0) + w
                    else:
                        pair = (min(la, lb), max(la, lb))
                        between[pair] = between.get(pair, 0.0) + w
        ratios = [
            (w / max(min(inside.get(a, 0.0), inside.get(b, 0.0)), 1e-9), pair)
            for pair, w in between.items()
            for a, b in [pair]
        ]
        best = max(ratios, default=None)
        if best is None or best[0] < 1.0:
            break
        keep, fold = best[1]
        for key, lab in label.items():
            if lab == fold:
                label[key] = keep
    groups: dict[str, list[str]] = {}
    for key, lab in label.items():
        groups.setdefault(lab, []).append(key)
    clusters = [sorted(g) for g in groups.values() if len(g) >= CLUSTER_MIN]
    return sorted(clusters, key=lambda g: (-len(g), g[0]))


class HealthService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.graph = GraphService(session)
        self.shelves = ShelfService(session)

    # ---- health -------------------------------------------------------------------------

    def project(self, project_id: str, view: dict | None = None) -> dict:
        view = view or self.graph.view(project_id)
        nodes, links = view["nodes"], view["links"]
        real = [link for link in links if link["status"] != "candidate"]
        clusters = self._named_clusters(view)
        since = utc_now() - RECENT
        return {
            "nodes": len(nodes),
            # Memory a link or shelf could lead an agent to (not in every pack, not manual only),
            # and how much of it nothing leads to: in a project only a word search finds it, in
            # the Global scope nothing does.
            "memory": sum(
                1
                for m in self.session.scalars(
                    select(Memory).where(
                        Memory.project_id == project_id,
                        Memory.status == "active",
                        Memory.ai_visibility.not_in(("hidden", "manual_only")),
                    )
                )
                if not in_every_pack(m)
            ),
            "links": len(real),
            "strong_links": sum(1 for link in real if link["strength"] >= STRONG_FROM),
            "weak_links": sum(1 for link in real if link["status"] == "weak"),
            "guessed_links": len(links) - len(real),
            "orphans": len(DiscoveryService(self.session).orphans(project_id, limit=1_000_000)),
            "conflicts": sum(1 for link in real if link["relationship"] == "contradicts"),
            "superseded": sum(1 for link in real if link["relationship"] == "supersedes"),
            "shelves": len(view["shelves"]),
            "clusters": [
                {
                    "name": c["name"],
                    "size": len(c["members"]),
                    "trend": self._trend(project_id, c["name"], len(c["members"])),
                }
                for c in clusters
            ],
            "density": self._density(view),
            "retrieval": self._retrieval(project_id),
            # Agents save a checkpoint after real work, so this is how often they worked lately.
            "checkpoints_recent": len(
                self.session.scalars(
                    select(Checkpoint.id).where(
                        Checkpoint.project_id == project_id, Checkpoint.created_at >= since
                    )
                ).all()
            ),
        }

    def workspace(self) -> dict:
        from app.services.context import PATH_CACHE_STATS

        projects = list(
            self.session.scalars(
                select(Project).where(Project.status != "archived").order_by(Project.name)
            )
        )
        out = []
        suggestions = []
        for project in sorted(projects, key=lambda p: p.id != GLOBAL_PROJECT_ID):
            view = self.graph.view(project.id)
            if not view["nodes"]:
                continue
            name = "Global rules" if project.id == GLOBAL_PROJECT_ID else project.name
            out.append({"id": project.id, "name": name, **self.project(project.id, view)})
            suggestions += [
                {**s, "project_id": project.id, "project_name": name}
                for s in self.suggestions(project.id, view)
            ]
        dismissed = set(self._dismissed())
        suggestions += [
            s for s in self.share_suggestions() if f"{s['project_id']}|{s['key']}" not in dismissed
        ]
        setting = self.session.get(AppSetting, DECAY_SETTING)
        return {
            "projects": out,
            "suggestions": suggestions,
            "last_decay": setting.value if setting else None,
            "path_cache": dict(PATH_CACHE_STATS),
        }

    def _trend(self, project_id: str, name: str, size: int) -> str | None:
        """'new' or 'growing' against the last daily snapshot; None when there is none yet."""
        row = self.session.get(AppSetting, CLUSTER_SNAPSHOT)
        if row is None or not row.value:
            return None
        before = (row.value.get("projects") or {}).get(project_id, {})
        if name not in before:
            return "new"
        return "growing" if size > before[name] else None

    def snapshot_clusters(self) -> None:
        """Automatic cluster discovery: record today's clusters for every project."""
        projects = {}
        for project in self.session.scalars(select(Project).where(Project.status != "archived")):
            view = self.graph.view(project.id)
            if view["nodes"]:
                projects[project.id] = {
                    c["name"]: len(c["members"]) for c in self._named_clusters(view)
                }
        row = self.session.get(AppSetting, CLUSTER_SNAPSHOT) or AppSetting(key=CLUSTER_SNAPSHOT)
        row.value = {"at": utc_now().isoformat(), "projects": projects}
        row.updated_at = utc_now()
        self.session.add(row)
        self.session.commit()

    def _retrieval(self, project_id: str) -> dict:
        rows = list(
            self.session.scalars(
                select(RetrievalSession).where(RetrievalSession.project_id == project_id)
            )
        )
        items = [i for r in rows for i in r.items]
        verdicts = Counter(i.get("verdict") for i in items if i.get("verdict"))
        rated = verdicts["useful"] + verdicts["not useful"]
        tokens = [r.tokens for r in rows if r.tokens]
        since = utc_now() - RECENT
        recent = [r for r in rows if r.created_at and _aware(r.created_at) >= since]
        return {
            "packs": len(rows),
            "packs_recent": len(recent),
            "feedback_recent": sum(1 for r in recent if r.outcome),
            # The share of records in packs that came in over links rather than a word search,
            # a shelf or the task itself: what the Link System adds to retrieval.
            "through_links": round(sum(1 for i in items if i.get("path")) / len(items), 2)
            if items
            else None,
            "average_depth": round(sum(len(i.get("path", [])) for i in items) / len(items), 2)
            if items
            else None,
            "average_records": round(len(items) / len(rows), 1) if rows else None,
            "average_tokens": round(sum(tokens) / len(tokens)) if tokens else None,
            "feedback_share": round(sum(1 for r in rows if r.outcome) / len(rows), 2)
            if rows
            else None,
            "useful_share": round(verdicts["useful"] / rated, 2) if rated else None,
        }

    @staticmethod
    def _density(view: dict) -> list[dict]:
        """Per shelf: the share of its records linked to another record on the same shelf."""
        members: dict[str, set[str]] = {}
        for n in view["nodes"]:
            for shelf_id in n["shelves"]:
                members.setdefault(shelf_id, set()).add(n["key"])
        linked: dict[str, set[str]] = {s: set() for s in members}
        for link in view["links"]:
            if link["status"] == "candidate":
                continue
            for shelf_id, keys in members.items():
                if link["source"] in keys and link["target"] in keys:
                    linked[shelf_id] |= {link["source"], link["target"]}
        names = {s["id"]: s["name"] for s in view["shelves"]}
        out = [
            {
                "shelf_id": shelf_id,
                "name": names.get(shelf_id, shelf_id),
                "records": len(keys),
                "connected": round(len(linked[shelf_id]) / len(keys), 2),
            }
            for shelf_id, keys in members.items()
            if keys and shelf_id in names
        ]
        return sorted(out, key=lambda d: (-d["records"], d["name"]))

    # ---- clusters and suggestions -------------------------------------------------------

    def _named_clusters(self, view: dict) -> list[dict]:
        # Titles only: labels (TRAI-012, DEC-3) would name every cluster after its prefix.
        titles = {n["key"]: n["title"] for n in view["nodes"]}
        everywhere = Counter(w for t in titles.values() for w in _words(t))
        total = max(len(titles), 1)
        by_key = {n["key"]: n for n in view["nodes"]}
        used: set[str] = set()
        out = []
        for members in find_clusters(view["nodes"], view["links"]):
            inside = Counter(w for k in members for w in _words(titles[k]))
            scored = [
                (n / len(members) - everywhere[w] / total, w)
                for w, n in inside.items()
                if n / len(members) >= NAME_SHARE
                and (everywhere[w] - n) / max(total - len(members), 1) < NAME_COMMON
                and w not in used
            ]
            word = max(scored)[1] if scored else None
            if word:
                used.add(word)
            hub = max(members, key=lambda k: (by_key[k]["degree"], k))
            # With no word of its own, a cluster is named after its best-linked record's title.
            title = by_key[hub]["title"] or by_key[hub]["label"]
            out.append(
                {
                    "name": word.capitalize() if word else _short(title),
                    "word": word,
                    "members": members,
                }
            )
        return out

    def suggestions(self, project_id: str, view: dict | None = None) -> list[dict]:
        view = view or self.graph.view(project_id)
        dismissed = set(self._dismissed())
        shelves = {s["id"]: s for s in view["shelves"]}
        on_shelf: dict[str, set[str]] = {s: set() for s in shelves}
        for n in view["nodes"]:
            for shelf_id in n["shelves"]:
                on_shelf.setdefault(shelf_id, set()).add(n["key"])
        taken = {name_key(s["name"]) for s in shelves.values()}
        titles = {n["key"]: n["title"] for n in view["nodes"]}
        out: list[dict] = []
        # Shelves are categories of knowledge (Game design > Game mechanics), never a word that
        # recurs in some titles: a cluster is offered the most specific existing shelf its
        # records name, or flagged as needing a category a person names.
        for cluster in self._named_clusters(view):
            members = set(cluster["members"])
            if not SUGGEST_MIN <= len(members) <= SUGGEST_MAX:
                continue
            key_name = name_key(cluster["name"])
            if key_name in taken:
                continue
            best = max(
                ((len(members & keys) / len(members), sid) for sid, keys in on_shelf.items()),
                default=(0.0, None),
            )
            share, shelf_id = best
            about = f"about {cluster['word']}" if cluster["word"] else f"around {cluster['name']}"
            if share >= COVERED:
                keys = on_shelf[shelf_id]
                if not (
                    cluster["word"]
                    and share >= SPLIT_INSIDE
                    and len(keys) >= SPLIT_FROM
                    and len(members) <= SPLIT_MAX * len(keys)
                ):
                    continue
                where = self._path(shelf_id, shelves)
                out.append(
                    {
                        "key": f"needs_category:{key_name}",
                        "kind": "needs_category",
                        "name": cluster["name"],
                        "keywords": [],
                        "parent": {"id": shelf_id, "name": where},
                        "members": sorted(members),
                        "size": len(members),
                        "message": f"{len(members)} records on {where} link mostly to each "
                        f"other {about}. If they form a narrower category, add it under "
                        f"{shelves[shelf_id]['name']} and file them there.",
                    }
                )
                continue
            target = self.shelves.suggest(
                project_id, " ".join(titles.get(k, "") for k in sorted(members))
            )
            if target is not None and target.id in shelves:
                out.append(
                    {
                        "key": f"place:{target.id}:{key_name}",
                        "kind": "place",
                        "name": target.path,
                        "keywords": [],
                        "parent": None,
                        "shelf": {"id": target.id, "name": target.path},
                        "members": sorted(members - on_shelf.get(target.id, set())),
                        "size": len(members),
                        "message": f"{len(members)} linked records {about} sit on no shelf. "
                        f"File them on {target.path}?",
                    }
                )
            else:
                out.append(
                    {
                        "key": f"needs_category:{key_name}",
                        "kind": "needs_category",
                        "name": cluster["name"],
                        "keywords": [],
                        "parent": None,
                        "members": sorted(members),
                        "size": len(members),
                        "message": f"{len(members)} linked records {about} fit no shelf yet. "
                        "Add the category they belong to in the knowledge tree and file them "
                        "there.",
                    }
                )
        out = sorted(out, key=lambda s: -s["size"])[:SUGGESTIONS_SHOWN]
        # Shelves of the shared tree are merged by hand: other projects file on them too.
        ids = sorted(
            s
            for s in on_shelf
            if s in shelves and not shelves[s].get("shared") and len(on_shelf[s]) >= 3
        )
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                union = on_shelf[a] | on_shelf[b]
                overlap = len(on_shelf[a] & on_shelf[b]) / len(union)
                if overlap < MERGE_FROM:
                    continue
                keep, fold = sorted((a, b), key=lambda s: (-len(on_shelf[s]), shelves[s]["name"]))
                out.append(
                    {
                        "key": f"merge:{fold}:{keep}",
                        "kind": "merge",
                        "name": shelves[keep]["name"],
                        "keywords": [],
                        "parent": None,
                        "merge_from": {"id": fold, "name": shelves[fold]["name"]},
                        "members": sorted(on_shelf[fold] - on_shelf[keep]),
                        "size": len(union),
                        "message": (
                            f"{shelves[fold]['name']} and {shelves[keep]['name']} hold mostly "
                            f"the same records ({round(overlap * 100)}%). Merge "
                            f"{shelves[fold]['name']} into {shelves[keep]['name']}?"
                        ),
                    }
                )
        out += self._shelf_tuning(project_id, view, shelves, on_shelf)
        out += self._patterns(view)
        by_key = {n["key"]: n for n in view["nodes"]}
        return [
            {**s, "records": _records(s["members"], by_key)}
            for s in out
            if f"{project_id}|{s['key']}" not in dismissed
        ]

    # ---- Phase 4: self-tuning shelves, patterns, sharing --------------------------------

    def _shelf_tuning(
        self, project_id: str, view: dict, shelves: dict, on_shelf: dict[str, set[str]]
    ) -> list[dict]:
        titles = {n["key"]: n["title"] for n in view["nodes"]}
        labels = {n["key"]: n["label"] for n in view["nodes"]}
        links: dict[str, list[tuple[str, float]]] = {}
        for link in view["links"]:
            if link["status"] != "active":
                continue
            links.setdefault(link["source"], []).append((link["target"], link["strength"]))
            links.setdefault(link["target"], []).append((link["source"], link["strength"]))
        everywhere = Counter(w for t in titles.values() for w in _words(t))
        total = max(len(titles), 1)
        adds, words, noise = [], [], []
        placed = {
            (r.shelf_id, f"{r.node_kind}:{r.node_id}")
            for r in self.session.scalars(
                select(ShelfMember).where(ShelfMember.shelf_id.in_(list(shelves)))
            )
        }
        noisy = {
            f"{r.node_kind}:{r.node_id}"
            for r in self.session.scalars(
                select(NodeUsefulness).where(NodeUsefulness.project_id == project_id)
            )
            if r.not_useful >= NOISE_VERDICTS and r.useful == 0
        }
        for shelf_id, shelf in shelves.items():
            members = on_shelf.get(shelf_id, set())
            if not members:
                continue
            # A shelf of lessons takes lessons, not every task that follows them.
            kinds = {k.partition(":")[0] for k in members}
            for key, ends in links.items():
                if key in members or key not in titles or key.partition(":")[0] not in kinds:
                    continue
                inside = [e for e, w in ends if e in members and w >= ADD_MEMBER_STRENGTH]
                if len(inside) >= ADD_MEMBER_LINKS and len(inside) / len(ends) >= ADD_MEMBER_SHARE:
                    adds.append(
                        {
                            "key": f"add_member:{shelf_id}:{key}",
                            "kind": "add_member",
                            "name": shelf["name"],
                            "shelf": {"id": shelf_id, "name": shelf["name"]},
                            "members": [key],
                            "size": len(inside),
                            "message": f"{labels[key]} ({titles[key][:60]}) links mostly to "
                            f"records on {shelf['name']} but is not on it. Add it?",
                        }
                    )
            if len(members) >= KEYWORD_MEMBERS:
                have = {name_key(w) for w in (shelf.get("keywords") or [])} | {
                    name_key(shelf["name"])
                }
                inside = Counter(w for k in members if k in titles for w in _words(titles[k]))
                for w, n in inside.most_common():
                    rest = (everywhere[w] - n) / max(total - len(members), 1)
                    if n / len(members) < KEYWORD_SHARE:
                        break
                    if rest < NAME_COMMON and name_key(w) not in have:
                        words.append(
                            {
                                "key": f"add_keyword:{shelf_id}:{w}",
                                "kind": "add_keyword",
                                "name": shelf["name"],
                                "shelf": {"id": shelf_id, "name": shelf["name"]},
                                "keywords": [w],
                                "members": [],
                                "size": n,
                                "message": f"{n} of the {len(members)} records on "
                                f"{shelf['name']} are about {w}. Let the shelf wake on '{w}'?",
                            }
                        )
                        break
            for key in sorted(noisy & members):
                if (shelf_id, key) in placed:  # tag members are the person's own tags
                    noise.append(
                        {
                            "key": f"remove_member:{shelf_id}:{key}",
                            "kind": "remove_member",
                            "name": shelf["name"],
                            "shelf": {"id": shelf_id, "name": shelf["name"]},
                            "members": [key],
                            "size": 1,
                            "message": f"Agents called {labels.get(key, key)} noise "
                            f"{NOISE_VERDICTS} or more times and never useful. Take it off "
                            f"{shelf['name']}?",
                        }
                    )
        return adds[:PER_KIND] + words[:PER_KIND] + noise[:PER_KIND]

    @staticmethod
    def _path(shelf_id: str, shelves: dict) -> str:
        names, seen, node = [], set(), shelf_id
        while node in shelves and node not in seen:
            names.insert(0, shelves[node]["name"])
            seen.add(node)
            node = shelves[node].get("parent_id")
        return " > ".join(names)

    def _patterns(self, view: dict) -> list[dict]:
        by_key = {n["key"]: n for n in view["nodes"]}
        out = []
        for cluster in self._named_clusters(view):
            issues = [k for k in cluster["members"] if by_key[k]["subtype"] in ("bug", "warning")]
            if len(issues) >= PATTERN_ISSUES and cluster["word"]:
                out.append(
                    {
                        "key": f"pattern:{cluster['word']}",
                        "kind": "pattern",
                        "name": cluster["name"],
                        "members": sorted(issues),
                        "size": len(issues),
                        "message": f"{len(issues)} bugs and warnings cluster around "
                        f"{cluster['word']}, a recurring failure area. A rule could stop the "
                        "next one.",
                    }
                )
        return sorted(out, key=lambda s: -s["size"])[:PER_KIND]

    def share_suggestions(self) -> list[dict]:
        """The same lesson written in two projects, worth one Global record."""
        from app.services.shelves import stem

        rows = list(
            self.session.scalars(
                select(Memory).where(
                    Memory.project_id != GLOBAL_PROJECT_ID,
                    Memory.status == "active",
                    Memory.type.in_(SHARE_TYPES),
                    Memory.ai_visibility != "hidden",
                )
            )
        )
        meaning = {m.id: {stem(w) for w in _words(m.title)} for m in rows}
        names = {
            p.id: p.name
            for p in self.session.scalars(select(Project).where(Project.status != "archived"))
        }
        out = []
        for i, a in enumerate(rows):
            for b in rows[i + 1 :]:
                if a.project_id == b.project_id or not {a.project_id, b.project_id} <= names.keys():
                    continue
                shared = meaning[a.id] & meaning[b.id]
                smaller = max(min(len(meaning[a.id]), len(meaning[b.id])), 1)
                if len(shared) < SHARE_WORDS or len(shared) / smaller < SHARE_OF:
                    continue
                first, second = sorted((a, b), key=lambda m: m.id)
                out.append(
                    {
                        "key": f"share:{first.id}:{second.id}",
                        "kind": "share",
                        "name": first.title,
                        "members": [f"memory:{first.id}", f"memory:{second.id}"],
                        "records": [
                            {"label": f"{names[m.project_id]} {m.human_id}", "title": m.title}
                            for m in (first, second)
                        ],
                        "size": 2,
                        "project_id": first.project_id,
                        "project_name": names[first.project_id],
                        "message": f"{names[first.project_id]} {first.human_id} and "
                        f"{names[second.project_id]} {second.human_id} say the same thing "
                        f'("{first.title[:50]}"). Make it one Global {first.type} both '
                        "projects link to?",
                    }
                )
        return out[:SUGGESTIONS_SHOWN]

    def _accept_share(self, key: str) -> dict:
        from app.services.graph import GraphService as Graph
        from app.services.memory import MemoryService

        found = next((s for s in self.share_suggestions() if s["key"] == key), None)
        if found is None:
            raise not_found("That suggestion no longer applies; the brain has changed since")
        _, a_id, b_id = key.split(":")
        a, b = self.session.get(Memory, a_id), self.session.get(Memory, b_id)
        created = MemoryService(self.session).create(
            GLOBAL_PROJECT_ID,
            MemoryCreate(
                type=a.type,
                title=a.title,
                content=a.content or "",
                importance=a.importance,
                source_type="shared",
                source_reference=f"{a.human_id} and {b.human_id}",
            ),
        )
        for m in (a, b):
            Graph(self.session).link(
                m.project_id,
                f"memory:{m.id}",
                "refines",
                f"global:{created.human_id}",
                strength=0.7,
                note="Shared as one Global record",
            )
        return {"memory_id": created.id, "name": created.human_id, "members": 2}

    def accept(self, project_id: str, key: str, actor: str = HUMAN) -> dict:
        if key.startswith("share:"):
            return self._accept_share(key)
        found = next((s for s in self.suggestions(project_id) if s["key"] == key), None)
        if found is None:
            raise not_found("That suggestion no longer applies; the brain has changed since")
        if found["kind"] == "pattern":
            raise invalid("A recurring failure area is a notice; write the rule yourself")
        if found["kind"] == "needs_category":
            raise invalid("Name the category yourself, then file the records on it")
        if found["kind"] in ("add_member", "add_keyword", "remove_member", "place"):
            return self._tune(project_id, found)
        return self._merge(project_id, found["merge_from"]["id"], key.split(":")[2], actor)

    def organize(self, project_id: str) -> dict:
        """Shelves keep themselves in order, with no one accepting each change: unfiled clusters
        are filed, records linked mostly into a shelf join it, noise leaves it, and shelves
        learn the words of the work their records helped with. Every change is in the activity
        log. Naming a new category is left to the agent at work (see crowded shelves in the
        context pack): a word picked by the app is not a category."""
        done: Counter[str] = Counter()
        for found in self.suggestions(project_id):
            if found["kind"] not in AUTO_KINDS:
                continue
            try:
                self._tune(project_id, found, actor=ORGANIZER)
                done[found["kind"]] += 1
            except Exception:  # noqa: BLE001 - one bad suggestion never stops the rest
                self.session.rollback()
        done["learned_word"] += self._learn_words(project_id)
        return dict(done)

    def _learn_words(self, project_id: str) -> int:
        row = self.session.get(AppSetting, WORD_EVIDENCE)
        if row is None or not row.value:
            return 0
        titles = [n["title"] for n in self.graph.view(project_id)["nodes"]]
        everywhere = Counter(w for t in titles for w in _words(t))
        total = max(len(titles), 1)
        evidence = dict(row.value)
        learned = 0
        for shelf_id, words in list(evidence.items()):
            shelf = self.session.get(Shelf, shelf_id)
            if shelf is None:
                evidence.pop(shelf_id)
                continue
            if shelf.project_id not in (project_id, GLOBAL_PROJECT_ID):
                continue
            ready = [
                w
                for w, ids in words.items()
                if len(set(ids)) >= LEARN_SESSIONS
                and w not in STATUS_WORDS
                and everywhere[w] / total < NAME_COMMON
            ]
            if not ready:
                continue
            have = [w.strip() for w in (shelf.keywords or "").split(",") if w.strip()]
            shelf.keywords = ",".join(dict.fromkeys([*have, *ready]))
            shelf.updated_at = utc_now()
            evidence[shelf_id] = {w: ids for w, ids in words.items() if w not in ready}
            self.shelves._log(shelf, "SHELF_UPDATED", ORGANIZER)
            learned += len(ready)
        row.value = evidence
        row.updated_at = utc_now()
        self.session.commit()
        return learned

    def _tune(self, project_id: str, found: dict, actor: str = HUMAN) -> dict:
        shelf = self.session.get(Shelf, found["shelf"]["id"])
        if found["kind"] in ("add_member", "place"):
            self.shelves.place(project_id, shelf.id, found["members"], actor=actor)
        elif found["kind"] == "add_keyword":
            words = [w.strip() for w in (shelf.keywords or "").split(",") if w.strip()]
            shelf.keywords = ",".join(dict.fromkeys([*words, *found["keywords"]]))
            self.shelves._log(shelf, "SHELF_UPDATED", actor)
        else:
            self.shelves._log(shelf, "SHELF_MEMBER_REMOVED", actor)
            node = _node(found["members"][0])
            for row in self.session.scalars(
                select(ShelfMember).where(
                    ShelfMember.shelf_id == shelf.id,
                    ShelfMember.node_kind == node.kind,
                    ShelfMember.node_id == node.id,
                )
            ):
                self.session.delete(row)
        shelf.updated_at = utc_now()
        self.session.commit()
        return {"shelf_id": shelf.id, "name": shelf.name, "members": len(found["members"])}

    def dismiss(self, project_id: str, key: str) -> None:
        row = self.session.get(AppSetting, DISMISSED) or AppSetting(key=DISMISSED, value=[])
        row.value = sorted({*(row.value or []), f"{project_id}|{key}"})
        row.updated_at = utc_now()
        self.session.add(row)
        self.session.commit()

    def _dismissed(self) -> list[str]:
        row = self.session.get(AppSetting, DISMISSED)
        return list(row.value or []) if row else []

    def _merge(self, project_id: str, fold_id: str, keep_id: str, actor: str) -> dict:
        fold = self.session.get(Shelf, fold_id)
        keep = self.session.get(Shelf, keep_id)
        if fold is None or keep is None or {fold.project_id, keep.project_id} != {project_id}:
            raise not_found("One of those shelves no longer exists")
        # Everything on the folded shelf, tagged or placed, now sits on the kept one.
        members = self.shelves.memberships(project_id, [fold])[fold.id]
        self._add_members(project_id, keep.id, list(members))
        for child in self.session.scalars(select(Shelf).where(Shelf.parent_id == fold.id)):
            child.parent_id = keep.id if child.id != keep.id else None
        if keep.parent_id == fold.id:
            keep.parent_id = fold.parent_id
        words = [w for w in (keep.keywords or "").split(",") + (fold.keywords or "").split(",")]
        keep.keywords = ",".join(dict.fromkeys(w.strip() for w in words if w.strip()))
        keep.updated_at = utc_now()
        self.session.flush()
        name = fold.name
        self.shelves.delete(project_id, fold.id, actor)
        return {"shelf_id": keep.id, "name": keep.name, "merged": name, "members": len(members)}

    def _add_members(self, project_id: str, shelf_id: str, nodes: list[Node]) -> None:
        """Puts the project's records on a shelf, its own or one of the shared tree."""
        owner = self.session.get(Shelf, shelf_id).project_id
        have = set(
            self.session.execute(
                select(ShelfMember.node_kind, ShelfMember.node_id).where(
                    ShelfMember.shelf_id == shelf_id
                )
            ).all()
        )
        now = utc_now()
        for node in nodes:
            if (node.kind, node.id) not in have:
                self.session.add(
                    ShelfMember(
                        shelf_id=shelf_id,
                        node_kind=node.kind,
                        node_id=node.id,
                        project_id=owner,
                        created_at=now,
                    )
                )
        self.session.flush()


def _short(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _records(keys: list[str], by_key: dict[str, dict]) -> list[dict]:
    """The first few records a suggestion would touch, by label and title."""
    return [
        {"label": by_key[k]["label"], "title": by_key[k]["title"]}
        for k in keys[:RECORDS_SHOWN]
        if k in by_key
    ]


def _node(key: str) -> Node:
    kind, _, node_id = key.partition(":")
    return Node(kind, node_id)
