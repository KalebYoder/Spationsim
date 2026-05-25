"""Tests for map generation helpers: richness weighting, territory classification,
dynamic generation, and seed output validation.

Written BEFORE implementation per TDD workflow.
"""
from __future__ import annotations

import random

import pytest
from sqlalchemy.orm import Session

from app.map_gen import (
    CLUSTER_CENTERS,
    CLUSTER_RADIUS,
    CLUSTER_VOID_RING,
    classify_hex,
    generate_territory,
    weighted_richness,
)
from app.models.territory import Territory
from app.seed import seed_territories


# ---------------------------------------------------------------------------
# Fake rng helpers
# ---------------------------------------------------------------------------

class _FixedRng:
    """Always triggers anomaly; mineral gets the richness value."""
    def __init__(self, richness_value: int = 7):
        self._richness = richness_value
        self._call = 0

    def random(self):
        self._call += 1
        # First call = anomaly check (< 0.001), second = resource selection (< 0.5 → mineral)
        return 0.0

    def randint(self, a, b):
        return self._richness

    def choices(self, population, weights=None):
        return [population[-1]]


class _FixedRngFuelAnomaly:
    """Always triggers anomaly; fuel gets the richness value."""
    def __init__(self, richness_value: int = 8):
        self._richness = richness_value
        self._call = 0

    def random(self):
        self._call += 1
        # First call = anomaly check → 0.0 (triggers), second = resource → 0.9 (fuel)
        return 0.0 if self._call <= 1 else 0.9

    def randint(self, a, b):
        return self._richness

    def choices(self, population, weights=None):
        return [population[0]]


# ---------------------------------------------------------------------------
# weighted_richness — unit tests
# ---------------------------------------------------------------------------

class TestWeightedRichness:
    def test_returns_integer(self):
        v = weighted_richness(0, random.Random(0))
        assert isinstance(v, int)

    def test_range_at_center(self):
        rng = random.Random(42)
        for _ in range(200):
            v = weighted_richness(0, rng)
            assert 1 <= v <= 5

    def test_range_at_rim(self):
        rng = random.Random(42)
        for _ in range(200):
            v = weighted_richness(CLUSTER_RADIUS, rng)
            assert 1 <= v <= 5

    def test_center_skewed_high(self):
        """≥50% of values at center should be 4 or 5."""
        rng = random.Random(7)
        results = [weighted_richness(0, rng) for _ in range(400)]
        high = sum(1 for v in results if v >= 4)
        assert high >= 200, f"Only {high}/400 were ≥4 at center"

    def test_rim_skewed_low(self):
        """≥50% of values at rim should be 1 or 2."""
        rng = random.Random(7)
        results = [weighted_richness(CLUSTER_RADIUS, rng) for _ in range(400)]
        low = sum(1 for v in results if v <= 2)
        assert low >= 200, f"Only {low}/400 were ≤2 at rim"

    def test_mean_decreases_with_distance(self):
        """Mean richness must not increase going outward from center."""
        rng = random.Random(99)
        means = []
        for dist in range(CLUSTER_RADIUS + 1):
            samples = [weighted_richness(dist, rng) for _ in range(400)]
            means.append(sum(samples) / len(samples))
        for i in range(len(means) - 1):
            assert means[i] >= means[i + 1] - 0.4, (
                f"Mean increased: dist={i} → {means[i]:.2f}, dist={i+1} → {means[i+1]:.2f}"
            )


# ---------------------------------------------------------------------------
# classify_hex — unit tests
# ---------------------------------------------------------------------------

class TestClassifyHex:
    def test_cluster_center_is_normal(self):
        cq, cr = CLUSTER_CENTERS[0]
        t_type, local_dist = classify_hex(cq, cr)
        assert t_type == "normal"
        assert local_dist == 0

    def test_inside_cluster_radius_is_normal(self):
        cq, cr = CLUSTER_CENTERS[0]
        t_type, local_dist = classify_hex(cq + 1, cr)
        assert t_type == "normal"
        assert local_dist == 1

    def test_at_cluster_rim_is_normal(self):
        cq, cr = CLUSTER_CENTERS[0]
        t_type, local_dist = classify_hex(cq + CLUSTER_RADIUS, cr)
        assert t_type == "normal"
        assert local_dist == CLUSTER_RADIUS

    def test_just_outside_cluster_is_void(self):
        cq, cr = CLUSTER_CENTERS[0]
        t_type, _ = classify_hex(cq + CLUSTER_RADIUS + 1, cr)
        assert t_type == "void"

    def test_at_void_ring_edge_is_void(self):
        cq, cr = CLUSTER_CENTERS[0]
        t_type, _ = classify_hex(cq + CLUSTER_RADIUS + CLUSTER_VOID_RING, cr)
        assert t_type == "void"

    def test_beyond_void_ring_is_void(self):
        cq, cr = CLUSTER_CENTERS[0]
        t_type, _ = classify_hex(cq + CLUSTER_RADIUS + CLUSTER_VOID_RING + 5, cr)
        assert t_type == "void"

    def test_deep_space_is_void(self):
        t_type, _ = classify_hex(100, 100)
        assert t_type == "void"

    def test_all_cluster_centers_are_normal(self):
        for cq, cr in CLUSTER_CENTERS:
            t_type, local_dist = classify_hex(cq, cr)
            assert t_type == "normal", f"Cluster center {cq},{cr} not classified as normal"
            assert local_dist == 0

    def test_local_dist_is_from_nearest_cluster(self):
        """Hex near two clusters returns dist from the closer one."""
        cq, cr = CLUSTER_CENTERS[0]
        t_type, local_dist = classify_hex(cq + 3, cr)
        assert local_dist == 3


# ---------------------------------------------------------------------------
# generate_territory — unit tests
# ---------------------------------------------------------------------------

class TestGenerateTerritory:
    def test_normal_territory_richness_integers_1_to_5(self):
        cq, cr = CLUSTER_CENTERS[0]
        rng = random.Random(42)
        t = generate_territory(cq, cr, rng)
        assert t.territory_type == "normal"
        m, f = float(t.mineral_richness), float(t.fuel_richness)
        assert m == int(m) and 1 <= m <= 5
        assert f == int(f) and 1 <= f <= 5

    def test_void_territory_richness_zero(self):
        cq, cr = CLUSTER_CENTERS[0]
        rng = random.Random(42)
        t = generate_territory(cq + CLUSTER_RADIUS + 2, cr, rng)
        assert t.territory_type in ("void", "anomaly")
        if t.territory_type == "void":
            assert float(t.mineral_richness) == 0.0
            assert float(t.fuel_richness) == 0.0

    def test_anomaly_mineral_shape(self):
        """With always-anomaly rng (mineral), mineral is 5-10 and fuel is 0."""
        cq, cr = CLUSTER_CENTERS[0]
        rng = _FixedRng(richness_value=7)
        t = generate_territory(cq + CLUSTER_RADIUS + 2, cr, rng)
        assert t.territory_type == "anomaly"
        m, f = float(t.mineral_richness), float(t.fuel_richness)
        assert 5 <= m <= 10
        assert f == 0.0

    def test_anomaly_fuel_shape(self):
        """With always-anomaly rng (fuel), fuel is 5-10 and mineral is 0."""
        cq, cr = CLUSTER_CENTERS[0]
        rng = _FixedRngFuelAnomaly(richness_value=8)
        t = generate_territory(cq + CLUSTER_RADIUS + 2, cr, rng)
        assert t.territory_type == "anomaly"
        m, f = float(t.mineral_richness), float(t.fuel_richness)
        assert m == 0.0
        assert 5 <= f <= 10

    def test_anomaly_richness_range(self):
        """Anomaly richness value must be 5-10."""
        cq, cr = CLUSTER_CENTERS[0]
        for v in range(5, 11):
            rng = _FixedRng(richness_value=v)
            t = generate_territory(cq + CLUSTER_RADIUS + 2, cr, rng)
            assert t.territory_type == "anomaly"
            max_r = max(float(t.mineral_richness), float(t.fuel_richness))
            assert max_r == v

    def test_anomaly_not_generated_in_cluster(self):
        """Anomaly rng should not produce anomaly inside a cluster (normal overrides)."""
        cq, cr = CLUSTER_CENTERS[0]
        rng = _FixedRng(richness_value=7)
        t = generate_territory(cq, cr, rng)
        # Even with always-anomaly rng, cluster centers are normal
        assert t.territory_type == "normal"

    def test_sets_node_key(self):
        t = generate_territory(3, 5, random.Random(0))
        assert t.node_key == "3,5"

    def test_sets_distance_from_center(self):
        cq, cr = CLUSTER_CENTERS[0]
        t = generate_territory(cq + 3, cr, random.Random(0))
        assert t.distance_from_center == 3

    def test_void_sets_distance_from_nearest_cluster(self):
        cq, cr = CLUSTER_CENTERS[0]
        t = generate_territory(cq + CLUSTER_RADIUS + 2, cr, random.Random(0))
        assert t.distance_from_center == CLUSTER_RADIUS + 2


# ---------------------------------------------------------------------------
# seed_territories integration tests
# ---------------------------------------------------------------------------

class TestSeedOutput:
    def _read_all(self):
        from app.db.database import SessionLocal
        s = SessionLocal()
        try:
            return s.query(Territory).all()
        finally:
            s.close()

    def test_seed_creates_territories(self, db: Session):
        seed_territories()
        all_t = self._read_all()
        assert len(all_t) > 0

    def test_normal_territories_integer_richness_1_to_5(self, db: Session):
        seed_territories()
        normals = [t for t in self._read_all() if t.territory_type == "normal"]
        assert len(normals) > 0
        for t in normals:
            m, f = float(t.mineral_richness), float(t.fuel_richness)
            assert m == int(m), f"mineral_richness {m} at {t.node_key} is not integer"
            assert 1 <= int(m) <= 5, f"mineral_richness {m} out of range at {t.node_key}"
            assert f == int(f), f"fuel_richness {f} at {t.node_key} is not integer"
            assert 1 <= int(f) <= 5

    def test_void_territories_have_zero_richness(self, db: Session):
        seed_territories()
        voids = [t for t in self._read_all() if t.territory_type == "void"]
        assert len(voids) > 0
        for t in voids:
            assert float(t.mineral_richness) == 0.0
            assert float(t.fuel_richness) == 0.0

    def test_no_duplicate_node_keys(self, db: Session):
        seed_territories()
        keys = [t.node_key for t in self._read_all()]
        assert len(keys) == len(set(keys)), "Duplicate node_keys found after seeding"

    def test_center_richness_higher_than_rim(self, db: Session):
        seed_territories()
        all_t = self._read_all()
        centers = [t for t in all_t if t.territory_type == "normal" and t.distance_from_center == 0]
        rim = [t for t in all_t if t.territory_type == "normal" and t.distance_from_center == CLUSTER_RADIUS]
        assert len(centers) > 0 and len(rim) > 0
        avg_center = sum(float(t.mineral_richness) + float(t.fuel_richness) for t in centers) / len(centers)
        avg_rim = sum(float(t.mineral_richness) + float(t.fuel_richness) for t in rim) / len(rim)
        assert avg_center > avg_rim, (
            f"Center avg {avg_center:.2f} must be > rim avg {avg_rim:.2f}"
        )

    def test_void_territories_outside_all_clusters(self, db: Session):
        seed_territories()
        voids = [t for t in self._read_all() if t.territory_type == "void"]
        assert len(voids) > 0
        for t in voids:
            q, r = (int(x) for x in t.node_key.split(","))
            min_dist = min(
                max(abs(q - cq), abs(r - cr), abs((q - cq) + (r - cr)))
                for cq, cr in CLUSTER_CENTERS
            )
            assert min_dist > CLUSTER_RADIUS, (
                f"Void territory {t.node_key} is inside a cluster (min_dist={min_dist})"
            )

    def test_territory_types_are_valid(self, db: Session):
        seed_territories()
        types = {t.territory_type for t in self._read_all()}
        valid = {"normal", "void", "anomaly"}
        assert types.issubset(valid), f"Unknown types: {types - valid}"

    def test_three_cluster_centers_seeded(self, db: Session):
        seed_territories()
        centers = [
            t for t in self._read_all()
            if t.territory_type == "normal" and t.distance_from_center == 0
        ]
        assert len(centers) == len(CLUSTER_CENTERS), (
            f"Expected {len(CLUSTER_CENTERS)} cluster centers, got {len(centers)}"
        )
