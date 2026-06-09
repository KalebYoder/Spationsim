"""Tests for probe pre-generation before movement.

Before this fix, a probe stalled for a full tick whenever _next_step() returned
a hex that hadn't been generated yet — territory_by_key.get(next_key) returned
None so the move was skipped.  The fix pre-generates nodes within PROBE_VISION_RADIUS
of the probe's CURRENT position before attempting movement, guaranteeing the
next step always exists.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.constants import PROBE_VISION_RADIUS
from app.map_gen import CLUSTER_CENTERS
from app.models.nation import Nation
from app.models.probe import Probe
from app.models.territory import Territory
from app.tasks.tick import run_tick


# ---------------------------------------------------------------------------
# Local helpers (avoid coupling tests to private tick internals)
# ---------------------------------------------------------------------------

def _hex_dist(q1, r1, q2, r2):
    dq, dr = q2 - q1, r2 - r1
    return max(abs(dq), abs(dr), abs(dq + dr))


def _next_step(cq, cr, dq, dr):
    neighbors = [
        (cq+1, cr), (cq-1, cr), (cq, cr+1),
        (cq, cr-1), (cq+1, cr-1), (cq-1, cr+1),
    ]
    return min(neighbors, key=lambda nb: _hex_dist(nb[0], nb[1], dq, dr))


def _commit_and_run_tick(db: Session) -> None:
    db.commit()
    run_tick()


def _territory_at(node_key: str, db: Session, nation_id: int | None = None) -> Territory:
    t = Territory(
        node_key=node_key,
        territory_type="normal",
        mineral_richness=3,
        fuel_richness=3,
        distance_from_center=1,
        nation_id=nation_id,
        is_owned=nation_id is not None,
        owned_at=datetime.now(timezone.utc) if nation_id else None,
    )
    db.add(t)
    db.flush()
    return t


def _in_transit_probe(current: Territory, dest: Territory, nation_id: int, db: Session) -> Probe:
    probe = Probe(
        nation_id=nation_id,
        origin_territory=current.id,
        current_territory=current.id,
        destination_territory=dest.id,
        status="in_transit",
    )
    db.add(probe)
    db.flush()
    return probe


def _fresh_probe(probe_id: int) -> Probe:
    from app.db.database import SessionLocal
    s = SessionLocal()
    try:
        return s.query(Probe).filter_by(id=probe_id).first()
    finally:
        s.close()


def _territory_exists(node_key: str) -> bool:
    from app.db.database import SessionLocal
    s = SessionLocal()
    try:
        return s.query(Territory).filter_by(node_key=node_key).first() is not None
    finally:
        s.close()


def _territory_by_key(node_key: str) -> Territory | None:
    from app.db.database import SessionLocal
    s = SessionLocal()
    try:
        return s.query(Territory).filter_by(node_key=node_key).first()
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProbePreGenerationBeforeMovement:

    def test_probe_moves_when_intermediate_node_missing(
        self, db: Session, test_nation: Nation
    ):
        """Core regression: probe advances one step in the same tick the
        missing intermediate node is generated, rather than stalling."""
        cq, cr = CLUSTER_CENTERS[0]         # (0, -16)
        origin = _territory_at(f"{cq},{cr}", db, nation_id=test_nation.id)
        # Destination 3 hops away; only origin and dest are pre-seeded
        dest = _territory_at(f"{cq+3},{cr}", db)

        probe = _in_transit_probe(origin, dest, test_nation.id, db)
        _commit_and_run_tick(db)

        refreshed = _fresh_probe(probe.id)
        assert refreshed.current_territory != origin.id, (
            "Probe did not move — it was blocked by a missing intermediate node"
        )

    def test_intermediate_node_generated_and_probe_moves_into_it(
        self, db: Session, test_nation: Nation
    ):
        """The node the probe moves into is persisted and the probe ends up there
        in the same tick, not one tick later."""
        cq, cr = CLUSTER_CENTERS[0]
        origin = _territory_at(f"{cq},{cr}", db, nation_id=test_nation.id)
        dest = _territory_at(f"{cq+3},{cr}", db)

        nq, nr = _next_step(cq, cr, cq+3, cr)  # (cq+1, cr)
        expected_key = f"{nq},{nr}"
        assert not _territory_exists(expected_key), (
            "Precondition failed: intermediate node must not exist before tick"
        )

        probe = _in_transit_probe(origin, dest, test_nation.id, db)
        _commit_and_run_tick(db)

        assert _territory_exists(expected_key), (
            f"Intermediate node {expected_key} was never created"
        )
        next_t = _territory_by_key(expected_key)
        refreshed = _fresh_probe(probe.id)
        assert refreshed.current_territory == next_t.id, (
            f"Probe should be at {expected_key} after tick, "
            f"but current_territory={refreshed.current_territory}"
        )

    def test_pre_generation_covers_full_radius_around_pre_move_position(
        self, db: Session, test_nation: Nation
    ):
        """All hexes within PROBE_VISION_RADIUS of the probe's PRE-movement
        position must exist in the DB after the tick."""
        cq, cr = CLUSTER_CENTERS[0]
        origin = _territory_at(f"{cq},{cr}", db, nation_id=test_nation.id)
        dest = _territory_at(f"{cq+5},{cr}", db)

        _in_transit_probe(origin, dest, test_nation.id, db)
        _commit_and_run_tick(db)

        for dq in range(-PROBE_VISION_RADIUS, PROBE_VISION_RADIUS + 1):
            for dr in range(-PROBE_VISION_RADIUS, PROBE_VISION_RADIUS + 1):
                if _hex_dist(0, 0, dq, dr) > PROBE_VISION_RADIUS:
                    continue
                key = f"{cq+dq},{cr+dr}"
                assert _territory_exists(key), (
                    f"Territory {key} (dist {_hex_dist(0, 0, dq, dr)} from origin) "
                    "missing after tick — pre-generation did not cover the origin radius"
                )

    def test_post_move_generation_covers_radius_around_new_position(
        self, db: Session, test_nation: Nation
    ):
        """After moving, the probe's new position also gets radius-2 coverage,
        ensuring next tick's movement is never blocked either."""
        cq, cr = CLUSTER_CENTERS[0]
        origin = _territory_at(f"{cq},{cr}", db, nation_id=test_nation.id)
        dest = _territory_at(f"{cq+5},{cr}", db)

        _in_transit_probe(origin, dest, test_nation.id, db)
        _commit_and_run_tick(db)

        # Probe moves to (cq+1, cr); its radius-2 ring must also exist
        new_q, new_r = _next_step(cq, cr, cq+5, cr)
        for dq in range(-PROBE_VISION_RADIUS, PROBE_VISION_RADIUS + 1):
            for dr in range(-PROBE_VISION_RADIUS, PROBE_VISION_RADIUS + 1):
                if _hex_dist(0, 0, dq, dr) > PROBE_VISION_RADIUS:
                    continue
                key = f"{new_q+dq},{new_r+dr}"
                assert _territory_exists(key), (
                    f"Territory {key} missing around post-move position "
                    f"({new_q},{new_r}) — forward-seeding for next tick failed"
                )

    def test_probe_advances_one_step_per_tick_through_uncharted_space(
        self, db: Session, test_nation: Nation
    ):
        """Probe must advance exactly one hex per tick even when the entire path
        is uncharted; no stalls across multiple ticks."""
        cq, cr = CLUSTER_CENTERS[0]
        origin = _territory_at(f"{cq},{cr}", db, nation_id=test_nation.id)
        dest = _territory_at(f"{cq+4},{cr}", db)

        probe = _in_transit_probe(origin, dest, test_nation.id, db)
        _commit_and_run_tick(db)

        step1_t = _territory_by_key(f"{cq+1},{cr}")
        assert step1_t is not None, "First intermediate node was not generated"
        after_tick1 = _fresh_probe(probe.id)
        assert after_tick1.current_territory == step1_t.id, (
            "Probe should be 1 step ahead after tick 1"
        )

        run_tick()  # tick 2 — no additional commit needed, data already committed

        step2_t = _territory_by_key(f"{cq+2},{cr}")
        assert step2_t is not None, "Second intermediate node was not generated"
        after_tick2 = _fresh_probe(probe.id)
        assert after_tick2.current_territory == step2_t.id, (
            "Probe should be 2 steps ahead after tick 2"
        )

    def test_stationed_probe_also_pre_generates_radius_2(
        self, db: Session, test_nation: Nation
    ):
        """Stationed probes (no movement) should also pre-generate the radius-2
        ring around their position so the invariant holds for all active probes."""
        cq, cr = CLUSTER_CENTERS[0]
        home = _territory_at(f"{cq},{cr}", db, nation_id=test_nation.id)
        probe = Probe(
            nation_id=test_nation.id,
            origin_territory=home.id,
            current_territory=home.id,
            destination_territory=None,
            status="stationed",
        )
        db.add(probe)
        _commit_and_run_tick(db)

        for dq in range(-PROBE_VISION_RADIUS, PROBE_VISION_RADIUS + 1):
            for dr in range(-PROBE_VISION_RADIUS, PROBE_VISION_RADIUS + 1):
                if _hex_dist(0, 0, dq, dr) > PROBE_VISION_RADIUS:
                    continue
                key = f"{cq+dq},{cr+dr}"
                assert _territory_exists(key), (
                    f"Territory {key} missing around stationed probe at ({cq},{cr}) — "
                    "pre-generation should apply to stationed probes too"
                )

    def test_no_duplicate_territories_created(
        self, db: Session, test_nation: Nation
    ):
        """Pre-generation and post-generation must not create duplicate rows
        when a territory already exists in the DB."""
        cq, cr = CLUSTER_CENTERS[0]
        origin = _territory_at(f"{cq},{cr}", db, nation_id=test_nation.id)
        dest = _territory_at(f"{cq+3},{cr}", db)

        # Pre-seed the intermediate node so both generation passes find it
        nq, nr = _next_step(cq, cr, cq+3, cr)
        _territory_at(f"{nq},{nr}", db)

        _in_transit_probe(origin, dest, test_nation.id, db)
        _commit_and_run_tick(db)

        from app.db.database import SessionLocal
        s = SessionLocal()
        try:
            all_keys = [t.node_key for t in s.query(Territory).all()]
            assert len(all_keys) == len(set(all_keys)), (
                "Duplicate node_key rows found after tick with pre-seeded intermediate node"
            )
        finally:
            s.close()
