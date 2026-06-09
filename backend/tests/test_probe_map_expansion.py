"""Integration tests for probe-driven dynamic territory generation.

When a probe scans a hex coordinate not yet in the DB, a new Territory row
must be created. These tests exercise that behaviour end-to-end via run_tick().

Written BEFORE implementation per TDD workflow.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.map_gen import CLUSTER_CENTERS, CLUSTER_RADIUS, CLUSTER_VOID_RING
from app.models.nation import Nation
from app.models.probe import Probe
from app.models.probe_data import ProbeData
from app.models.territory import Territory
from app.tasks.tick import run_tick
from app.constants import PROBE_VISION_RADIUS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _commit_and_run_tick(db: Session) -> None:
    db.commit()
    run_tick()


def _fresh_territories() -> list[Territory]:
    from app.db.database import SessionLocal
    s = SessionLocal()
    try:
        return s.query(Territory).all()
    finally:
        s.close()


def _fresh_probe_data() -> list[ProbeData]:
    from app.db.database import SessionLocal
    s = SessionLocal()
    try:
        return s.query(ProbeData).all()
    finally:
        s.close()


def _hex_dist(q1, r1, q2, r2):
    dq, dr = q2 - q1, r2 - r1
    return max(abs(dq), abs(dr), abs(dq + dr))


def _territory_at(node_key: str, nation_id: int, db: Session) -> Territory:
    q, r = (int(x) for x in node_key.split(","))
    t = Territory(
        node_key=node_key,
        territory_type="normal",
        mineral_richness=3,
        fuel_richness=3,
        distance_from_center=0,
        nation_id=nation_id,
        is_owned=True,
        owned_at=datetime.now(timezone.utc),
    )
    db.add(t)
    db.flush()
    return t


def _stationed_probe(territory: Territory, nation_id: int, db: Session) -> Probe:
    probe = Probe(
        nation_id=nation_id,
        origin_territory=territory.id,
        current_territory=territory.id,
        destination_territory=None,
        status="stationed",
    )
    db.add(probe)
    db.flush()
    return probe


# ---------------------------------------------------------------------------
# Tests: territory creation around stationed probe
# ---------------------------------------------------------------------------

class TestProbeCreatesNewTerritories:

    def test_stationed_probe_creates_surrounding_territories(
        self, db: Session, test_nation: Nation
    ):
        """Probe scans PROBE_VISION_RADIUS=2 hexes around itself; each uncharted hex
        becomes a Territory row after the tick."""
        cq, cr = CLUSTER_CENTERS[0]  # (0, -16) — cluster center
        home = _territory_at(f"{cq},{cr}", test_nation.id, db)
        _stationed_probe(home, test_nation.id, db)

        _commit_and_run_tick(db)

        territories = _fresh_territories()
        # 19 hexes total within radius 2 (1 + 6 + 12), all should be generated
        assert len(territories) >= 7, (
            f"Expected many new territories, got {len(territories)}"
        )

    def test_new_territories_within_vision_radius_only(
        self, db: Session, test_nation: Nation
    ):
        """No territory outside probe vision radius should be created."""
        cq, cr = CLUSTER_CENTERS[0]
        home = _territory_at(f"{cq},{cr}", test_nation.id, db)
        _stationed_probe(home, test_nation.id, db)

        _commit_and_run_tick(db)

        territories = _fresh_territories()
        for t in territories:
            tq, tr = (int(x) for x in t.node_key.split(","))
            dist = _hex_dist(cq, cr, tq, tr)
            assert dist <= PROBE_VISION_RADIUS, (
                f"Territory at {t.node_key} is dist={dist} from probe, "
                f"beyond PROBE_VISION_RADIUS={PROBE_VISION_RADIUS}"
            )

    def test_new_territories_in_cluster_have_normal_type(
        self, db: Session, test_nation: Nation
    ):
        """All hexes within cluster radius from probe should be created as 'normal'."""
        cq, cr = CLUSTER_CENTERS[0]
        home = _territory_at(f"{cq},{cr}", test_nation.id, db)
        _stationed_probe(home, test_nation.id, db)

        _commit_and_run_tick(db)

        territories = _fresh_territories()
        for t in territories:
            tq, tr = (int(x) for x in t.node_key.split(","))
            dist_from_cluster = _hex_dist(cq, cr, tq, tr)
            if dist_from_cluster <= CLUSTER_RADIUS:
                assert t.territory_type in ("normal", "anomaly"), (
                    f"Territory {t.node_key} in cluster has type {t.territory_type!r}"
                )

    def test_new_normal_territories_have_integer_richness_1_to_5(
        self, db: Session, test_nation: Nation
    ):
        """Newly generated normal territories must have integer richness 1-5."""
        cq, cr = CLUSTER_CENTERS[0]
        home = _territory_at(f"{cq},{cr}", test_nation.id, db)
        _stationed_probe(home, test_nation.id, db)

        _commit_and_run_tick(db)

        territories = _fresh_territories()
        normals = [t for t in territories if t.territory_type == "normal"]
        assert len(normals) > 0
        for t in normals:
            m, f = float(t.mineral_richness), float(t.fuel_richness)
            assert m == int(m) and 1 <= m <= 5, (
                f"mineral_richness {m} at {t.node_key} out of range"
            )
            assert f == int(f) and 1 <= f <= 5, (
                f"fuel_richness {f} at {t.node_key} out of range"
            )

    def test_existing_territory_not_duplicated(
        self, db: Session, test_nation: Nation
    ):
        """If a neighbouring territory already exists, the tick must not duplicate it."""
        cq, cr = CLUSTER_CENTERS[0]
        home = _territory_at(f"{cq},{cr}", test_nation.id, db)

        # Pre-seed a neighbour
        neighbour = Territory(
            node_key=f"{cq+1},{cr}",
            territory_type="normal",
            mineral_richness=2,
            fuel_richness=2,
            distance_from_center=1,
        )
        db.add(neighbour)
        db.flush()

        _stationed_probe(home, test_nation.id, db)
        _commit_and_run_tick(db)

        territories = _fresh_territories()
        keys = [t.node_key for t in territories]
        assert len(keys) == len(set(keys)), "Duplicate node_key found after tick"
        # The pre-seeded neighbour should still exist with original richness
        from app.db.database import SessionLocal
        s = SessionLocal()
        try:
            refreshed = s.query(Territory).filter_by(node_key=f"{cq+1},{cr}").first()
            assert refreshed is not None
            assert float(refreshed.mineral_richness) == 2.0
            assert float(refreshed.fuel_richness) == 2.0
        finally:
            s.close()

    def test_probe_at_rim_creates_void_territory_beyond_cluster(
        self, db: Session, test_nation: Nation
    ):
        """Probe at cluster rim generates void territory for hexes outside cluster radius."""
        cq, cr = CLUSTER_CENTERS[0]  # (0, -16)
        # Place probe at rim: (CLUSTER_RADIUS, -16) = (7, -16)
        rim_q, rim_r = cq + CLUSTER_RADIUS, cr
        home = _territory_at(f"{rim_q},{rim_r}", test_nation.id, db)
        _stationed_probe(home, test_nation.id, db)

        _commit_and_run_tick(db)

        territories = _fresh_territories()
        void_count = 0
        for t in territories:
            tq, tr = (int(x) for x in t.node_key.split(","))
            # Find territories outside all cluster radii
            min_dist_all = min(
                _hex_dist(cq2, cr2, tq, tr) for cq2, cr2 in CLUSTER_CENTERS
            )
            if min_dist_all > CLUSTER_RADIUS:
                assert t.territory_type in ("void", "anomaly"), (
                    f"Territory {t.node_key} outside clusters has type {t.territory_type!r}"
                )
                if t.territory_type == "void":
                    void_count += 1
        assert void_count > 0, "Expected at least one void territory beyond cluster rim"

    def test_void_territories_have_zero_richness(
        self, db: Session, test_nation: Nation
    ):
        """Void territories generated by probe must have zero richness."""
        cq, cr = CLUSTER_CENTERS[0]
        rim_q, rim_r = cq + CLUSTER_RADIUS, cr
        home = _territory_at(f"{rim_q},{rim_r}", test_nation.id, db)
        _stationed_probe(home, test_nation.id, db)

        _commit_and_run_tick(db)

        territories = _fresh_territories()
        for t in territories:
            if t.territory_type == "void":
                assert float(t.mineral_richness) == 0.0
                assert float(t.fuel_richness) == 0.0

    def test_probe_data_recorded_for_new_normal_territories(
        self, db: Session, test_nation: Nation
    ):
        """ProbeData entries are created for every normal territory the probe reveals."""
        cq, cr = CLUSTER_CENTERS[0]
        home = _territory_at(f"{cq},{cr}", test_nation.id, db)
        _stationed_probe(home, test_nation.id, db)

        _commit_and_run_tick(db)

        territories = _fresh_territories()
        probe_data = _fresh_probe_data()

        normal_ids = {t.id for t in territories if t.territory_type == "normal"}
        probed_ids = {pd.territory_id for pd in probe_data}

        assert normal_ids.issubset(probed_ids), (
            f"Missing ProbeData for territory ids: {normal_ids - probed_ids}"
        )

    def test_probe_data_not_recorded_for_void_territories(
        self, db: Session, test_nation: Nation
    ):
        """Void territories must not produce ProbeData entries."""
        cq, cr = CLUSTER_CENTERS[0]
        rim_q, rim_r = cq + CLUSTER_RADIUS, cr
        home = _territory_at(f"{rim_q},{rim_r}", test_nation.id, db)
        _stationed_probe(home, test_nation.id, db)

        _commit_and_run_tick(db)

        territories = _fresh_territories()
        probe_data = _fresh_probe_data()

        void_ids = {t.id for t in territories if t.territory_type == "void"}
        probed_ids = {pd.territory_id for pd in probe_data}
        assert void_ids.isdisjoint(probed_ids), (
            f"ProbeData created for void territory ids: {void_ids & probed_ids}"
        )

    def test_second_tick_does_not_regenerate_territories(
        self, db: Session, test_nation: Nation
    ):
        """Running tick twice must not create duplicates or overwrite existing territories."""
        cq, cr = CLUSTER_CENTERS[0]
        home = _territory_at(f"{cq},{cr}", test_nation.id, db)
        _stationed_probe(home, test_nation.id, db)

        _commit_and_run_tick(db)
        first_count = len(_fresh_territories())

        run_tick()  # second tick
        second_count = len(_fresh_territories())

        assert second_count == first_count, (
            f"Second tick changed territory count: {first_count} → {second_count}"
        )

    def test_new_territory_distance_from_center_set_correctly(
        self, db: Session, test_nation: Nation
    ):
        """Newly generated territories must have distance_from_center = dist from nearest cluster."""
        cq, cr = CLUSTER_CENTERS[0]
        home = _territory_at(f"{cq},{cr}", test_nation.id, db)
        _stationed_probe(home, test_nation.id, db)

        _commit_and_run_tick(db)

        territories = _fresh_territories()
        for t in territories:
            tq, tr = (int(x) for x in t.node_key.split(","))
            expected_dist = min(
                _hex_dist(c_q, c_r, tq, tr) for c_q, c_r in CLUSTER_CENTERS
            )
            assert t.distance_from_center == expected_dist, (
                f"Territory {t.node_key}: expected dist={expected_dist}, "
                f"got {t.distance_from_center}"
            )
