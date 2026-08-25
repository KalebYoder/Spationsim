from __future__ import annotations

from collections import deque


def compute_reachable_ids(
    source_key: str, nation_id: int, territories: list[dict]
) -> set[int]:
    """
    BFS reachability for fleet dispatch.

    Phase 1 traverses through tiles that are passable (own nation or unclaimed,
    non-void).  The source tile is always included regardless of ownership, and
    BFS always starts from it.

    Phase 2 adds enemy/foreign-owned destinations that are adjacent to a
    passable non-source reachable tile — fleets may enter such tiles to attack,
    but cannot use them as stepping stones.

    Void tiles are impassable walls and never appear in the result.
    """
    by_key: dict[str, dict] = {t["node_key"]: t for t in territories}

    source = by_key.get(source_key)
    if source is None:
        return set()

    def _neighbors(key: str):
        q, r = map(int, key.split(","))
        for dq, dr in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)):
            nkey = f"{q + dq},{r + dr}"
            if nkey in by_key:
                yield nkey, by_key[nkey]

    def _passable(t: dict) -> bool:
        return t["territory_type"] != "void" and (
            t["nation_id"] is None or t["nation_id"] == nation_id
        )

    # Phase 1: BFS through passable tiles only.
    # Source is always in the frontier (we explore from it regardless of its owner).
    reachable: set[int] = {source["id"]}
    passable_non_source: set[str] = set()
    visited: set[str] = {source_key}
    queue: deque[str] = deque([source_key])

    while queue:
        current_key = queue.popleft()
        for nkey, neighbor in _neighbors(current_key):
            if nkey in visited:
                continue
            visited.add(nkey)
            if _passable(neighbor):
                reachable.add(neighbor["id"])
                passable_non_source.add(nkey)
                queue.append(nkey)

    # Phase 2: non-void foreign tiles adjacent to a passable non-source reachable
    # tile are dispatchable targets (fleet enters to attack, cannot pass through).
    for key, t in by_key.items():
        if t["territory_type"] == "void":
            continue
        if t["nation_id"] is None or t["nation_id"] == nation_id:
            continue
        if t["id"] in reachable:
            continue
        q, r = map(int, key.split(","))
        for dq, dr in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)):
            if f"{q + dq},{r + dr}" in passable_non_source:
                reachable.add(t["id"])
                break

    return reachable


def compute_path(
    source_key: str, dest_key: str, nation_id: int, territories: list[dict]
) -> list[dict] | None:
    """
    BFS shortest path from source to dest using the same passability rules as
    compute_reachable_ids. Returns territory dicts from source to dest inclusive,
    or None if the destination is unreachable.
    """
    by_key: dict[str, dict] = {t["node_key"]: t for t in territories}

    if source_key not in by_key or dest_key not in by_key:
        return None
    if source_key == dest_key:
        return [by_key[source_key]]

    def _neighbors(key: str):
        q, r = map(int, key.split(","))
        for dq, dr in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)):
            nkey = f"{q + dq},{r + dr}"
            if nkey in by_key:
                yield nkey

    def _passable(t: dict) -> bool:
        return t["territory_type"] != "void" and (
            t["nation_id"] is None or t["nation_id"] == nation_id
        )

    parent: dict[str, str | None] = {source_key: None}
    queue: deque[str] = deque([source_key])

    while queue:
        current_key = queue.popleft()
        for nkey in _neighbors(current_key):
            if nkey in parent:
                continue
            neighbor = by_key[nkey]
            if _passable(neighbor) or nkey == dest_key:
                parent[nkey] = current_key
                if nkey == dest_key:
                    path: list[dict] = []
                    k: str | None = dest_key
                    while k is not None:
                        path.append(by_key[k])
                        k = parent[k]
                    return list(reversed(path))
                queue.append(nkey)

    return None
