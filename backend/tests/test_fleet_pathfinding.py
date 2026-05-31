"""
Test suite for fleet reachability / pathfinding.

Tests the function:
    compute_reachable_ids(source_key: str, nation_id: int, territories: list[dict]) -> set[int]

which lives in app.services.pathfinding.

Pathfinding rules under test:
  - A fleet may traverse its own territories and unclaimed (nation_id=None) territories.
  - A fleet may NOT traverse territories owned by another nation.
  - Void territories (territory_type == 'void') are impassable — treated as walls.
  - Source and destination are always included in the path check regardless of ownership.
  - Two hexes are adjacent when hex_distance == 1:
        max(|dq|, |dr|, |dq+dr|) == 1

Territory dict shape:
    {
        "id": int,
        "node_key": "q,r",
        "territory_type": str,   # "planet" or "void"
        "nation_id": int | None,
    }

No fixtures are used — territory lists are built inline so each test is readable
in isolation.
"""

from __future__ import annotations

import pytest

from app.services.pathfinding import compute_reachable_ids


# ---------------------------------------------------------------------------
# Hex grid helpers (mirrors the implementation spec)
# ---------------------------------------------------------------------------


def _hex_dist(q1: int, r1: int, q2: int, r2: int) -> int:
    dq, dr = q2 - q1, r2 - r1
    return max(abs(dq), abs(dr), abs(dq + dr))


def _t(
    id: int,
    node_key: str,
    *,
    territory_type: str = "planet",
    nation_id: int | None = None,
) -> dict:
    """Convenience constructor for a territory dict."""
    return {
        "id": id,
        "node_key": node_key,
        "territory_type": territory_type,
        "nation_id": nation_id,
    }


# Nation IDs used across tests
OWN = 1
ENEMY = 2


# ===========================================================================
# 1. Isolated source — only the source itself is reachable
# ===========================================================================


def test_isolated_source_returns_only_source():
    """
    Source territory has no adjacent passable tiles.
    All six hex-neighbors are missing from the territory list.
    Only the source ID must be returned.
    """
    territories = [
        _t(1, "0,0", nation_id=OWN),
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert result == {1}, (
        "With no adjacent tiles, only the source itself should be reachable"
    )


# ===========================================================================
# 2. Direct neighbor — destination is 1 hex away with no owner
# ===========================================================================


def test_direct_unclaimed_neighbor_is_reachable():
    """
    Source is at 0,0 (own).  Destination at 1,0 is 1 hex away and unclaimed.
    Both IDs must appear in the result.
    """
    territories = [
        _t(1, "0,0", nation_id=OWN),
        _t(2, "1,0", nation_id=None),   # unclaimed, directly adjacent
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert 1 in result, "Source must always be in the reachable set"
    assert 2 in result, "Directly adjacent unclaimed tile must be reachable"


# ===========================================================================
# 3. Enemy wall — no way around; destination unreachable
# ===========================================================================


def test_enemy_wall_blocks_destination():
    """
    Layout (q,r coords):
        0,0  OWN source
        1,0  ENEMY — blocks the only path
        2,0  unclaimed destination

    The hex at 1,0 is the only passable step between source and 2,0.
    The enemy owns it, so 2,0 is unreachable.
    """
    territories = [
        _t(1, "0,0", nation_id=OWN),
        _t(2, "1,0", nation_id=ENEMY),   # wall
        _t(3, "2,0", nation_id=None),     # target, cut off
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert 1 in result, "Source must still be in the reachable set"
    assert 3 not in result, (
        "Destination behind an enemy territory with no alternate route must be unreachable"
    )


def test_enemy_wall_does_not_include_wall_tile():
    """
    The enemy-owned tile used as a wall must not appear in the reachable set.
    """
    territories = [
        _t(1, "0,0", nation_id=OWN),
        _t(2, "1,0", nation_id=ENEMY),
        _t(3, "2,0", nation_id=None),
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert 2 not in result, "Enemy-owned tiles are impassable and must not appear in reachable set"


# ===========================================================================
# 4. Path around enemy — longer route; destination reachable
# ===========================================================================


def test_path_around_enemy_reaches_destination():
    """
    Layout:
        0,0   OWN  (source)
        1,0   ENEMY (direct path blocked)
        2,0   unclaimed (destination)
        0,1   unclaimed (detour step 1)
        1,1   unclaimed (detour step 2 — neighbor of 2,0 via the hex grid)

    Hex distance check:
        (0,1) adj to (0,0): max(0,1,1)=1  OK
        (1,1) adj to (0,1): max(1,0,1)=1  OK
        (2,0) adj to (1,1): max(1,1,0)=1  OK  (dq=1, dr=-1, dq+dr=0)

    So path 0,0 -> 0,1 -> 1,1 -> 2,0 skirts the enemy at 1,0.
    """
    territories = [
        _t(1, "0,0", nation_id=OWN),
        _t(2, "1,0", nation_id=ENEMY),   # direct path blocked
        _t(3, "2,0", nation_id=None),     # destination
        _t(4, "0,1", nation_id=None),     # detour A
        _t(5, "1,1", nation_id=None),     # detour B — neighbor of 2,0
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert 3 in result, (
        "Destination must be reachable via the longer path skirting the enemy tile"
    )
    assert 4 in result, "Detour tile 0,1 must be reachable"
    assert 5 in result, "Detour tile 1,1 must be reachable"


# ===========================================================================
# 5. Void wall — void tiles block movement the same as enemy tiles
# ===========================================================================


def test_void_wall_blocks_movement():
    """
    A void tile at 1,0 must be treated as impassable even though it has no owner.
    The tile at 2,0 (unclaimed planet) is unreachable.
    """
    territories = [
        _t(1, "0,0", nation_id=OWN),
        _t(2, "1,0", territory_type="void", nation_id=None),   # void wall
        _t(3, "2,0", nation_id=None),
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert 2 not in result, "Void tiles are impassable — must not appear in reachable set"
    assert 3 not in result, (
        "Tile beyond a void wall with no alternate route must be unreachable"
    )


def test_void_wall_equivalent_to_enemy_wall():
    """
    A void wall and an enemy wall with no alternate route both produce the same
    outcome: destination is unreachable.
    """
    # Void wall scenario
    t_void = [
        _t(1, "0,0", nation_id=OWN),
        _t(2, "1,0", territory_type="void", nation_id=None),
        _t(3, "2,0", nation_id=None),
    ]
    result_void = compute_reachable_ids("0,0", OWN, t_void)

    # Enemy wall scenario — same geometry
    t_enemy = [
        _t(1, "0,0", nation_id=OWN),
        _t(2, "1,0", nation_id=ENEMY),
        _t(3, "2,0", nation_id=None),
    ]
    result_enemy = compute_reachable_ids("0,0", OWN, t_enemy)

    assert 3 not in result_void, "Void wall must block destination"
    assert 3 not in result_enemy, "Enemy wall must block destination"


def test_void_tile_passable_if_alternate_route_exists():
    """
    With a detour available, the destination is still reachable even when the
    direct path is a void tile.  The detour must not include the void tile.
    """
    territories = [
        _t(1, "0,0", nation_id=OWN),
        _t(2, "1,0", territory_type="void", nation_id=None),   # void on direct path
        _t(3, "2,0", nation_id=None),                           # destination
        _t(4, "0,1", nation_id=None),                           # detour A
        _t(5, "1,1", nation_id=None),                           # detour B
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert 3 in result, "Destination must be reachable via the detour around the void tile"
    assert 2 not in result, "Void tile itself must never appear in the reachable set"


# ===========================================================================
# 6. Destination owned by enemy — reachable via valid approach path
# ===========================================================================


def test_enemy_destination_reachable_via_valid_path():
    """
    The destination tile is owned by the enemy, but the path to reach it is
    unobstructed.  The function must include the destination in the reachable set
    because destination ownership is irrelevant — only traversal tiles matter.

    Path:  0,0 (OWN) -> 1,0 (unclaimed) -> 2,0 (ENEMY destination)
    """
    territories = [
        _t(1, "0,0", nation_id=OWN),
        _t(2, "1,0", nation_id=None),    # passable traversal tile
        _t(3, "2,0", nation_id=ENEMY),   # destination owned by enemy
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert 3 in result, (
        "Enemy-owned destination must be reachable when the approach path is clear. "
        "Only traversal (intermediate) tiles are restricted — not the destination itself."
    )


def test_enemy_destination_unreachable_when_path_blocked():
    """
    If the only approach path to an enemy destination runs through another enemy
    tile, the destination is unreachable.
    """
    territories = [
        _t(1, "0,0", nation_id=OWN),
        _t(2, "1,0", nation_id=ENEMY),   # blocking enemy tile
        _t(3, "2,0", nation_id=ENEMY),   # enemy destination
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert 3 not in result, (
        "Enemy destination must be unreachable when only path runs through another enemy tile"
    )


# ===========================================================================
# 7. Disconnected map — multiple clusters; only same-cluster tiles reachable
# ===========================================================================


def test_disconnected_clusters_only_source_cluster_reachable():
    """
    Two clusters of tiles separated by a gap (no adjacent connection).
    Only tiles in the same cluster as the source must appear in the result.

    Cluster A:  0,0 (OWN, source), 1,0 (unclaimed)
    Cluster B:  5,0 (unclaimed), 6,0 (unclaimed)  — separated by an empty gap
    """
    territories = [
        # Cluster A
        _t(1, "0,0", nation_id=OWN),
        _t(2, "1,0", nation_id=None),
        # Cluster B (no hex in cluster A is adjacent to any hex in cluster B)
        _t(3, "5,0", nation_id=None),
        _t(4, "6,0", nation_id=None),
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert 1 in result, "Source must be in the reachable set"
    assert 2 in result, "Tile adjacent to source must be reachable"
    assert 3 not in result, "Tile in disconnected cluster must NOT be reachable"
    assert 4 not in result, "Tile in disconnected cluster must NOT be reachable"


def test_disconnected_only_source_returned_when_isolated():
    """
    Tiles exist in the territory list but none are adjacent to the source.
    Result must contain only the source.
    """
    territories = [
        _t(1, "0,0", nation_id=OWN),   # source
        _t(2, "5,5", nation_id=None),   # far away, no path
        _t(3, "5,6", nation_id=None),   # far away, no path
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert result == {1}


# ===========================================================================
# 8. Own territory chain as a corridor
# ===========================================================================


def test_own_territory_corridor_connects_distant_friendly_tile():
    """
    A contiguous chain of own territories creates a corridor through which the
    fleet can reach a distant own territory.

    Layout (all OWN):  0,0 -> 1,0 -> 2,0 -> 3,0
    """
    territories = [
        _t(1, "0,0", nation_id=OWN),   # source
        _t(2, "1,0", nation_id=OWN),
        _t(3, "2,0", nation_id=OWN),
        _t(4, "3,0", nation_id=OWN),   # distant own territory
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert result == {1, 2, 3, 4}, (
        "Entire own-territory chain must be reachable from the source"
    )


def test_own_territory_corridor_mixed_with_unclaimed():
    """
    Mix of own and unclaimed tiles in a chain — all traversable.
    """
    territories = [
        _t(1, "0,0", nation_id=OWN),
        _t(2, "1,0", nation_id=None),   # unclaimed step
        _t(3, "2,0", nation_id=OWN),    # own territory further along
        _t(4, "3,0", nation_id=None),
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert {1, 2, 3, 4} == result, (
        "Mixed own/unclaimed chain must be fully reachable"
    )


# ===========================================================================
# 9. All neighbours are enemy-owned — only source returned
# ===========================================================================


def test_only_source_returned_when_all_neighbors_are_enemy():
    """
    All six hex-neighbors of the source are owned by the enemy.
    No tile beyond the source should be reachable.
    Result must be exactly {source_id}.

    The six axial neighbors of 0,0 are:
        (1,0), (-1,0), (0,1), (0,-1), (1,-1), (-1,1)
    """
    territories = [
        _t(1,  "0,0",  nation_id=OWN),    # source
        _t(2,  "1,0",  nation_id=ENEMY),
        _t(3,  "-1,0", nation_id=ENEMY),
        _t(4,  "0,1",  nation_id=ENEMY),
        _t(5,  "0,-1", nation_id=ENEMY),
        _t(6,  "1,-1", nation_id=ENEMY),
        _t(7,  "-1,1", nation_id=ENEMY),
        # A tile two steps away that would be reachable if the ring weren't blocking it
        _t(8,  "2,0",  nation_id=None),
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert result == {1}, (
        "When all neighbors are enemy-owned, only the source must be reachable"
    )


# ===========================================================================
# 10. Large contiguous unclaimed field — BFS reaches the far end
# ===========================================================================


def test_large_unclaimed_field_reaches_far_end():
    """
    A rectangular strip of unclaimed tiles from (0,0) to (9,0).
    All tiles are adjacent along the q-axis (each step has hex_dist == 1).
    BFS must traverse all of them and return all IDs.

    Tiles: (0,0) OWN source, (1,0) through (9,0) unclaimed.
    """
    territories = [_t(0, "0,0", nation_id=OWN)]
    for q in range(1, 10):
        territories.append(_t(q, f"{q},0", nation_id=None))

    result = compute_reachable_ids("0,0", OWN, territories)
    expected = set(range(0, 10))
    assert expected == result, (
        "BFS must reach every tile in a contiguous unclaimed strip"
    )


def test_large_unclaimed_field_does_not_cross_void_barrier():
    """
    A void tile at 5,0 splits a ten-tile strip into two halves.
    BFS from 0,0 must reach tiles 0-4 but not tiles 5-9.
    """
    territories = [_t(0, "0,0", nation_id=OWN)]
    for q in range(1, 5):
        territories.append(_t(q, f"{q},0", nation_id=None))
    # void barrier
    territories.append(_t(5, "5,0", territory_type="void", nation_id=None))
    for q in range(6, 10):
        territories.append(_t(q, f"{q},0", nation_id=None))

    result = compute_reachable_ids("0,0", OWN, territories)
    reachable_keys = {0, 1, 2, 3, 4}
    blocked_keys = {5, 6, 7, 8, 9}

    assert reachable_keys <= result, (
        "Tiles on the source side of the void barrier must all be reachable"
    )
    assert not (blocked_keys & result), (
        "Tiles on the far side of the void barrier must not be reachable"
    )


# ===========================================================================
# 11. Source node key not present in territory list — empty result
# ===========================================================================


def test_unknown_source_key_returns_empty_set():
    """
    If source_key does not match any territory in the list, the function must
    return an empty set (no crash, no fabricated IDs).
    """
    territories = [
        _t(1, "1,0", nation_id=OWN),
        _t(2, "2,0", nation_id=None),
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert result == set(), (
        "A source_key that doesn't exist in the territory list must return an empty set"
    )


# ===========================================================================
# 12. Empty territory list — empty result
# ===========================================================================


def test_empty_territory_list_returns_empty_set():
    """
    An empty territory list must produce an empty set without raising.
    """
    result = compute_reachable_ids("0,0", OWN, [])
    assert result == set()


# ===========================================================================
# 13. Source owned by enemy — source is still the starting point (the function
#     takes nation_id as the dispatching nation; the source may not be owned)
# ===========================================================================


def test_source_included_regardless_of_source_owner():
    """
    The feature spec states source is always included in the path check.
    Even if the source tile is owned by a different nation, it must appear in
    the result (it is the departure point passed explicitly by the caller).
    """
    territories = [
        _t(1, "0,0", nation_id=ENEMY),   # source is enemy-owned (edge case)
        _t(2, "1,0", nation_id=None),
    ]
    # The caller is dispatching from "0,0" for OWN nation — source always included
    result = compute_reachable_ids("0,0", OWN, territories)
    assert 1 in result, (
        "Source tile must always be included in the reachable set regardless of ownership"
    )


# ===========================================================================
# 14. Hex adjacency: verify the max-of-abs formula for all six neighbors
# ===========================================================================


def test_all_six_axial_neighbors_reachable():
    """
    Each of the six axial neighbors of 0,0 must be reachable individually.
    This verifies the adjacency formula covers all six hex directions.

    Axial neighbors of (q=0, r=0):
        (+1, 0), (-1, 0), (0, +1), (0, -1), (+1, -1), (-1, +1)
    """
    neighbor_keys = ["1,0", "-1,0", "0,1", "0,-1", "1,-1", "-1,1"]

    for i, nkey in enumerate(neighbor_keys):
        territories = [
            _t(1, "0,0", nation_id=OWN),
            _t(2, nkey,   nation_id=None),
        ]
        result = compute_reachable_ids("0,0", OWN, territories)
        assert 2 in result, (
            f"Neighbor at {nkey!r} must be reachable — "
            f"check that hex_distance formula covers the {nkey!r} direction"
        )


def test_non_adjacent_tile_not_treated_as_neighbor():
    """
    A tile at distance 2 from the source (e.g. 2,0) with no intermediate tile
    must NOT be reachable — the BFS cannot teleport.
    """
    territories = [
        _t(1, "0,0", nation_id=OWN),
        _t(2, "2,0", nation_id=None),   # distance 2, no intermediate
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert 2 not in result, (
        "A tile at hex distance 2 with no intermediate tile must not be directly reachable"
    )


# ===========================================================================
# 15. Third-party nation (not OWN, not ENEMY) blocks movement
# ===========================================================================


def test_third_party_nation_territory_blocks_movement():
    """
    A territory owned by a third nation (not OWN, not neutral) must also block
    traversal — only own and unclaimed tiles are passable.
    """
    THIRD = 3
    territories = [
        _t(1, "0,0", nation_id=OWN),
        _t(2, "1,0", nation_id=THIRD),   # third-party nation, not OWN
        _t(3, "2,0", nation_id=None),
    ]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert 2 not in result, "Third-party territory must be impassable"
    assert 3 not in result, "Tile beyond third-party wall with no alternate route must be unreachable"


# ===========================================================================
# 16. Return type is always a set (even with a single source tile)
# ===========================================================================


def test_return_type_is_set():
    """
    compute_reachable_ids must always return a set, never a list or None.
    """
    territories = [_t(1, "0,0", nation_id=OWN)]
    result = compute_reachable_ids("0,0", OWN, territories)
    assert isinstance(result, set), (
        f"compute_reachable_ids must return a set, got {type(result).__name__!r}"
    )
