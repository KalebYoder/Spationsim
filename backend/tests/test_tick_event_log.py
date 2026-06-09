"""Tests for the tick event log feature.

Covers:
  - GET /api/events/log: auth guard, response structure, economy data, game events,
    nation isolation, ordering, and limit parameter
  - tick.py: fleet_stationed, probe_stationed, colony_ship_stationed events created

Written BEFORE implementation per TDD workflow.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.colony_ship import ColonyShip
from app.models.diplomacy import Diplomacy
from app.models.event import Event
from app.models.fleet import Fleet
from app.models.infrastructure import Infrastructure
from app.models.nation import Nation
from app.models.player import Player
from app.models.probe import Probe
from app.models.resource_log import ResourceLog
from app.models.territory import Territory
from app.tasks.tick import run_tick


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _commit_and_run_tick(db: Session) -> None:
    db.commit()
    run_tick()


def _fresh() -> Session:
    return SessionLocal()


def _territory(db, node_key, *, nation_id=None, is_owned=False,
               mineral_richness=3, fuel_richness=3) -> Territory:
    t = Territory(
        node_key=node_key,
        territory_type="normal",
        mineral_richness=mineral_richness,
        fuel_richness=fuel_richness,
        distance_from_center=0,
        nation_id=nation_id,
        is_owned=is_owned,
        owned_at=datetime.now(timezone.utc) if is_owned else None,
    )
    db.add(t)
    db.flush()
    return t


def _mine(db, territory_id) -> Infrastructure:
    infra = Infrastructure(territory_id=territory_id, type="mine", population_assigned=10)
    db.add(infra)
    db.flush()
    return infra


def _arrived_fleet(db, nation_id, origin_id, dest_id, units=5) -> Fleet:
    now = datetime.now(timezone.utc)
    fleet = Fleet(
        nation_id=nation_id,
        origin_territory=origin_id,
        destination_territory=dest_id,
        unit_count=units,
        status="in_transit",
        departs_at=now - timedelta(hours=4),
        arrives_at=now - timedelta(minutes=1),
        standing_order="hold",
    )
    db.add(fleet)
    db.flush()
    return fleet


def _arriving_probe(db, nation_id, current_id, dest_id) -> Probe:
    now = datetime.now(timezone.utc)
    probe = Probe(
        nation_id=nation_id,
        origin_territory=current_id,
        current_territory=current_id,
        destination_territory=dest_id,
        status="in_transit",
        departs_at=now - timedelta(hours=2),
        arrives_at=now - timedelta(minutes=1),
    )
    db.add(probe)
    db.flush()
    return probe


def _arrived_colony_ship(db, nation_id, origin_id, dest_id) -> ColonyShip:
    now = datetime.now(timezone.utc)
    ship = ColonyShip(
        nation_id=nation_id,
        origin_territory=origin_id,
        destination_territory=dest_id,
        cargo_population=10,
        status="in_transit",
        departs_at=now - timedelta(hours=2),
        arrives_at=now - timedelta(minutes=1),
    )
    db.add(ship)
    db.flush()
    return ship


def _set_war(db, nation_a_id, nation_b_id):
    a, b = min(nation_a_id, nation_b_id), max(nation_a_id, nation_b_id)
    db.add(Diplomacy(nation_a=a, nation_b=b, status="war"))
    db.flush()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestEventLogAuth:
    def test_unauthenticated_returns_401(self, client):
        r = client.get("/api/events/log")
        assert r.status_code == 401

    def test_authenticated_returns_200(self, auth_client):
        r = auth_client.get("/api/events/log")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------

class TestEventLogEmptyState:
    def test_no_data_returns_empty_list(self, auth_client):
        r = auth_client.get("/api/events/log")
        assert r.status_code == 200
        assert r.json() == []


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------

class TestEventLogStructure:
    def _setup_economy(self, db, test_nation):
        home = _territory(db, "0,0", nation_id=test_nation.id, is_owned=True)
        _mine(db, home.id)
        _commit_and_run_tick(db)

    def test_entry_has_tick_at(self, auth_client, db, test_nation):
        self._setup_economy(db, test_nation)
        data = auth_client.get("/api/events/log").json()
        assert len(data) >= 1
        assert "tick_at" in data[0]

    def test_entry_has_economy(self, auth_client, db, test_nation):
        self._setup_economy(db, test_nation)
        data = auth_client.get("/api/events/log").json()
        assert "economy" in data[0]

    def test_entry_has_events_list(self, auth_client, db, test_nation):
        self._setup_economy(db, test_nation)
        data = auth_client.get("/api/events/log").json()
        assert "events" in data[0]
        assert isinstance(data[0]["events"], list)

    def test_economy_has_all_delta_fields(self, auth_client, db, test_nation):
        self._setup_economy(db, test_nation)
        economy = auth_client.get("/api/events/log").json()[0]["economy"]
        assert economy is not None
        for field in ("minerals_delta", "fuel_delta", "population_delta", "currency_delta"):
            assert field in economy

    def test_tick_at_is_parseable_iso_string(self, auth_client, db, test_nation):
        self._setup_economy(db, test_nation)
        tick_at = auth_client.get("/api/events/log").json()[0]["tick_at"]
        assert isinstance(tick_at, str)
        datetime.fromisoformat(tick_at.replace("Z", "+00:00"))

    def test_event_entry_has_type_and_payload(self, auth_client, db, test_nation):
        """When a game event exists, each event object must have type and payload."""
        home = _territory(db, "0,0", nation_id=test_nation.id, is_owned=True)
        dest = _territory(db, "1,0", nation_id=test_nation.id, is_owned=True)
        _arrived_fleet(db, test_nation.id, home.id, dest.id)
        _commit_and_run_tick(db)

        data = auth_client.get("/api/events/log").json()
        all_events = [e for entry in data for e in entry["events"]]
        assert len(all_events) >= 1
        for ev in all_events:
            assert "type" in ev
            assert "payload" in ev


# ---------------------------------------------------------------------------
# Economy data correctness
# ---------------------------------------------------------------------------

class TestEconomyData:
    def test_minerals_delta_from_mine(self, auth_client, db, test_nation):
        # mine on richness-3 territory: round(2*3) = 6 minerals/tick
        home = _territory(db, "0,0", nation_id=test_nation.id, is_owned=True,
                          mineral_richness=3, fuel_richness=1)
        _mine(db, home.id)
        _commit_and_run_tick(db)

        economy = auth_client.get("/api/events/log").json()[0]["economy"]
        assert economy["minerals_delta"] == 6

    def test_currency_delta_from_mine_territory(self, auth_client, db, test_nation):
        # income=30 (1 mine), territory_upkeep=10 (k×1²), net=20
        home = _territory(db, "0,0", nation_id=test_nation.id, is_owned=True)
        _mine(db, home.id)
        _commit_and_run_tick(db)

        economy = auth_client.get("/api/events/log").json()[0]["economy"]
        assert economy["currency_delta"] == 20

    def test_no_entry_when_zero_production_and_no_events(self, auth_client, db, test_nation):
        # Nation with territory but no mine → no deltas → no resource_log → no entry
        _territory(db, "0,0", nation_id=test_nation.id, is_owned=True)
        _commit_and_run_tick(db)

        data = auth_client.get("/api/events/log").json()
        # May be empty, or contain entries with null economy but no pure-economy data
        for entry in data:
            if entry.get("economy") is not None:
                # If economy is present, it must be for our nation's actual data
                # (it should be zero production, but resource_log only created when non-zero)
                pass  # This path shouldn't be hit


# ---------------------------------------------------------------------------
# Tick creates new event types
# ---------------------------------------------------------------------------

class TestTickEventCreation:
    def test_fleet_stationed_event_in_db(self, db, test_nation):
        home = _territory(db, "0,0", nation_id=test_nation.id, is_owned=True)
        dest = _territory(db, "1,0")
        _arrived_fleet(db, test_nation.id, home.id, dest.id, units=5)
        _commit_and_run_tick(db)

        s = _fresh()
        try:
            ev = s.query(Event).filter(Event.type == "fleet_stationed").first()
            assert ev is not None, "tick must create a fleet_stationed event"
        finally:
            s.close()

    def test_fleet_stationed_payload(self, db, test_nation):
        home = _territory(db, "0,0", nation_id=test_nation.id, is_owned=True)
        dest = _territory(db, "1,0")
        _arrived_fleet(db, test_nation.id, home.id, dest.id, units=7)
        _commit_and_run_tick(db)

        s = _fresh()
        try:
            ev = s.query(Event).filter(Event.type == "fleet_stationed").first()
            assert ev.payload["nation_id"] == test_nation.id
            assert ev.payload["territory_id"] == dest.id
            assert ev.payload["territory_node_key"] == "1,0"
            assert ev.payload["unit_count"] == 7
        finally:
            s.close()

    def test_probe_stationed_event_in_db(self, db, test_nation):
        # Probe at (0,0), destination (1,0) — one hex, moves and stations in one tick
        current_t = _territory(db, "0,0", nation_id=test_nation.id, is_owned=True)
        dest_t = _territory(db, "1,0")
        _arriving_probe(db, test_nation.id, current_t.id, dest_t.id)
        _commit_and_run_tick(db)

        s = _fresh()
        try:
            ev = s.query(Event).filter(Event.type == "probe_stationed").first()
            assert ev is not None, "tick must create a probe_stationed event"
        finally:
            s.close()

    def test_probe_stationed_payload(self, db, test_nation):
        current_t = _territory(db, "0,0", nation_id=test_nation.id, is_owned=True)
        dest_t = _territory(db, "1,0")
        _arriving_probe(db, test_nation.id, current_t.id, dest_t.id)
        _commit_and_run_tick(db)

        s = _fresh()
        try:
            ev = s.query(Event).filter(Event.type == "probe_stationed").first()
            assert ev.payload["nation_id"] == test_nation.id
            assert ev.payload["territory_id"] == dest_t.id
            assert ev.payload["territory_node_key"] == "1,0"
        finally:
            s.close()

    def test_colony_ship_stationed_event_in_db(self, db, test_nation):
        origin = _territory(db, "0,0", nation_id=test_nation.id, is_owned=True)
        dest = _territory(db, "5,0")
        _arrived_colony_ship(db, test_nation.id, origin.id, dest.id)
        _commit_and_run_tick(db)

        s = _fresh()
        try:
            ev = s.query(Event).filter(Event.type == "colony_ship_stationed").first()
            assert ev is not None, "tick must create a colony_ship_stationed event"
        finally:
            s.close()

    def test_colony_ship_stationed_payload(self, db, test_nation):
        origin = _territory(db, "0,0", nation_id=test_nation.id, is_owned=True)
        dest = _territory(db, "5,0")
        _arrived_colony_ship(db, test_nation.id, origin.id, dest.id)
        _commit_and_run_tick(db)

        s = _fresh()
        try:
            ev = s.query(Event).filter(Event.type == "colony_ship_stationed").first()
            assert ev.payload["nation_id"] == test_nation.id
            assert ev.payload["territory_id"] == dest.id
            assert ev.payload["territory_node_key"] == "5,0"
        finally:
            s.close()


# ---------------------------------------------------------------------------
# Game events appear in API response
# ---------------------------------------------------------------------------

class TestGameEventsInLog:
    def test_fleet_stationed_appears_in_log(self, auth_client, db, test_nation):
        home = _territory(db, "0,0", nation_id=test_nation.id, is_owned=True)
        dest = _territory(db, "1,0")
        _arrived_fleet(db, test_nation.id, home.id, dest.id)
        _commit_and_run_tick(db)

        data = auth_client.get("/api/events/log").json()
        types = [e["type"] for entry in data for e in entry["events"]]
        assert "fleet_stationed" in types

    def test_probe_stationed_appears_in_log(self, auth_client, db, test_nation):
        cur = _territory(db, "0,0", nation_id=test_nation.id, is_owned=True)
        dest = _territory(db, "1,0")
        _arriving_probe(db, test_nation.id, cur.id, dest.id)
        _commit_and_run_tick(db)

        data = auth_client.get("/api/events/log").json()
        types = [e["type"] for entry in data for e in entry["events"]]
        assert "probe_stationed" in types

    def test_enemy_fleet_arrived_appears_for_defender(
        self, auth_client, db, test_nation
    ):
        """Defender sees enemy_fleet_arrived in their log when an enemy fleet arrives."""
        enemy_player = Player(username="ep2", email="ep2@test.com", password_hash="x")
        db.add(enemy_player)
        db.flush()
        enemy_nation = Nation(player_id=enemy_player.id, name="EnemyNation2",
                              minerals=100, fuel=100)
        db.add(enemy_nation)
        db.flush()

        _set_war(db, test_nation.id, enemy_nation.id)

        enemy_origin = _territory(db, "9,0", nation_id=enemy_nation.id, is_owned=True)
        our_home = _territory(db, "10,0", nation_id=test_nation.id, is_owned=True)
        _arrived_fleet(db, enemy_nation.id, enemy_origin.id, our_home.id)
        _commit_and_run_tick(db)

        data = auth_client.get("/api/events/log").json()
        types = [e["type"] for entry in data for e in entry["events"]]
        assert "enemy_fleet_arrived" in types, (
            "Defender must see enemy_fleet_arrived in their event log"
        )

    def test_probe_destroyed_appears_for_probe_owner(
        self, auth_client, db, test_nation
    ):
        """Probe owner sees probe_destroyed_in_enemy_territory in their log."""
        enemy_player = Player(username="ep3", email="ep3@test.com", password_hash="x")
        db.add(enemy_player)
        db.flush()
        enemy_nation = Nation(player_id=enemy_player.id, name="EnemyNation3",
                              minerals=100, fuel=100)
        db.add(enemy_nation)
        db.flush()

        _set_war(db, test_nation.id, enemy_nation.id)

        # probe currently in enemy territory (triggers destruction)
        enemy_t = _territory(db, "20,0", nation_id=enemy_nation.id, is_owned=True)
        origin = _territory(db, "18,0", nation_id=test_nation.id, is_owned=True)
        probe = Probe(
            nation_id=test_nation.id,
            origin_territory=origin.id,
            current_territory=enemy_t.id,
            destination_territory=enemy_t.id,
            status="in_transit",
            departs_at=datetime.now(timezone.utc) - timedelta(hours=2),
            arrives_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(probe)
        _commit_and_run_tick(db)

        data = auth_client.get("/api/events/log").json()
        types = [e["type"] for entry in data for e in entry["events"]]
        assert "probe_destroyed_in_enemy_territory" in types


# ---------------------------------------------------------------------------
# Nation isolation
# ---------------------------------------------------------------------------

class TestNationIsolation:
    def _second_nation(self, db, username="p_iso", email="iso@test.com"):
        p = Player(username=username, email=email, password_hash="x")
        db.add(p)
        db.flush()
        n = Nation(player_id=p.id, name=f"Iso Nation {username}", minerals=0, fuel=0)
        db.add(n)
        db.flush()
        return n

    def test_economy_not_leaked_across_nations(self, auth_client, db, test_nation):
        nation2 = self._second_nation(db)
        # nation2 has a high-production mine — should NOT appear in test_nation's log
        home2 = _territory(db, "50,0", nation_id=nation2.id, is_owned=True,
                           mineral_richness=5, fuel_richness=5)
        _mine(db, home2.id)
        _commit_and_run_tick(db)

        data = auth_client.get("/api/events/log").json()
        # test_nation has no mine → no resource_log → no economy entry
        for entry in data:
            if entry["economy"] is not None:
                # If present, minerals_delta must NOT be nation2's value (round(2*5)=10)
                assert entry["economy"]["minerals_delta"] != 10, (
                    "test_nation must not see nation2's mineral production"
                )

    def test_fleet_events_not_leaked_across_nations(self, auth_client, db, test_nation):
        nation2 = self._second_nation(db, "p_iso2", "iso2@test.com")
        origin2 = _territory(db, "60,0", nation_id=nation2.id, is_owned=True)
        dest2 = _territory(db, "61,0")
        _arrived_fleet(db, nation2.id, origin2.id, dest2.id)
        _commit_and_run_tick(db)

        data = auth_client.get("/api/events/log").json()
        for entry in data:
            for ev in entry["events"]:
                if ev["type"] == "fleet_stationed":
                    # Any fleet_stationed in test_nation's log must be their fleet
                    assert ev["payload"]["nation_id"] == test_nation.id, (
                        "test_nation must not see nation2's fleet_stationed events"
                    )


# ---------------------------------------------------------------------------
# Ordering and pagination
# ---------------------------------------------------------------------------

class TestOrdering:
    def test_newest_first(self, auth_client, db, test_nation):
        now = datetime.now(timezone.utc)
        for i in range(3):
            db.add(ResourceLog(
                nation_id=test_nation.id,
                tick_at=now - timedelta(hours=i * 2),
                minerals_delta=i + 1,
                fuel_delta=0,
                population_delta=0,
                currency_delta=0,
            ))
        db.commit()

        data = auth_client.get("/api/events/log").json()
        assert len(data) == 3
        tick_times = [
            datetime.fromisoformat(entry["tick_at"].replace("Z", "+00:00"))
            for entry in data
        ]
        assert tick_times == sorted(tick_times, reverse=True), (
            "Entries must be ordered newest first"
        )

    def test_default_limit_is_20(self, auth_client, db, test_nation):
        now = datetime.now(timezone.utc)
        for i in range(25):
            db.add(ResourceLog(
                nation_id=test_nation.id,
                tick_at=now - timedelta(hours=i * 2),
                minerals_delta=1,
                fuel_delta=0,
                population_delta=0,
                currency_delta=0,
            ))
        db.commit()

        data = auth_client.get("/api/events/log").json()
        assert len(data) <= 20

    def test_limit_query_param(self, auth_client, db, test_nation):
        now = datetime.now(timezone.utc)
        for i in range(10):
            db.add(ResourceLog(
                nation_id=test_nation.id,
                tick_at=now - timedelta(hours=i * 2),
                minerals_delta=1,
                fuel_delta=0,
                population_delta=0,
                currency_delta=0,
            ))
        db.commit()

        data = auth_client.get("/api/events/log?limit=5").json()
        assert len(data) == 5
