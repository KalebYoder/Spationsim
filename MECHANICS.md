# Spationsim — Mechanics Reference

*Quick reference for how each game system works and how long things take. For design decisions and rationale, see `nationsim_spec.md`. For code locations, see `CODEBASE.md`.*

*Tick = 2 hours real time. All durations expressed in both ticks and real hours.*

---

## Tick System

- Fires every **2 hours** via Celery beat
- One tick processes: resource generation, population growth, fleet movement, probe movement, construction completion, combat, dissent, upkeep deductions
- Players receive event log entries for everything that happened while they were offline

---

## Economy

### Resources
| Resource | Produced by | Used for |
|---|---|---|
| Minerals | Mines | Construction, fighters, colony ships |
| Fuel | Refineries | Fleet movement, probes, colony ships, upkeep |
| Currency | Facilities (30¤/tick per active mine or refinery) | Construction, fighters, probes, upkeep |
| Population | Organic growth (1%/tick, capped by richness) | Staffs facilities; consumed at fighter manufacture |

### Production rates
- Normal territory (richness 1–5): `max(5, round(richness × 2))` minerals or fuel per tick per facility
- Anomaly territory (richness 5–10): `round(richness × 2 + 10)` per tick per facility
- Range: 5–10/tick normal, 20–30/tick anomaly

### Upkeep (deducted each tick)
| Cost | Formula |
|---|---|
| Fighter currency | 2¤/tick per fighter (all statuses) |
| Fighter fuel | 1 fuel/tick per fighter not docked on own territory |
| Territory logistics fuel | `LOGISTICS_FUEL_K × N(N+1)/2` fuel/tick (N = territories owned; k=1) |
| Territory count currency | `TERRITORY_UPKEEP_K × N²` ¤/tick (k=10) |

**Population cap per territory:** `50 × (mineral_richness + fuel_richness)`

---

## Construction

All facilities are built at the territory level. Construction takes 1–2 ticks; resources deducted immediately on queue.

| Facility | Cost | Build time | Pop assigned | Effect |
|---|---|---|---|---|
| Mine | 60 min + 30 fuel + 500¤ | 1 tick (2h) | 10 | Produces minerals each tick |
| Refinery | 30 min + 60 fuel + 500¤ | 1 tick (2h) | 10 | Produces fuel each tick |
| Shipyard | 150 min + 60 fuel + 2000¤ | 2 ticks (4h) | 40 | Builds fighters, colony ships, probes |
| Propaganda Office | (TBD) | 1 tick (2h) | (TBD) | Accelerates dissent decay |

**Cancellation:** Any `under_construction` facility can be cancelled via `DELETE /api/facilities/{id}/cancel` for a full resource refund.

**Demolition:** Active facilities can be demolished for `DEMOLISH_REFUND_FRACTION` (25%) of all resource costs.

### Units (manufactured at shipyard — instant, no tick required)

| Unit | Cost | Pop consumed | Speed | Notes |
|---|---|---|---|---|
| Starfighter | 15 min + 30 fuel + 1000¤ | 1 (permanent) | 2 nodes/tick | FP 2, Shields 1, SI 5 |
| Colony ship | 500 min + 1000 fuel | 0 at build; 100 pop loaded | 1 node/tick | Carries population to claimed territory |
| Probe | 1000 min + 500 fuel + 10000¤ | 0 | 1 node/tick | Scouts destination richness |

---

## Exploration

### Probes
1. Manufacture probe at shipyard (instant)
2. Dispatch to destination — probe travels 1 node/tick
3. On arrival: destination tile gets `probe_data` (richness); path tiles get `probe_visibility` (existence only, no richness)
4. **Range:** up to 10 nodes from nearest owned colony
5. **Detection:** territory owner is notified when your probe transits their space; probe destroyed if nations are at war
6. **Recall:** in-transit probes can be recalled via the Probes page; may be destroyed transiting enemy space during war
7. **Probe data** can be sold on the public marketplace; seller retains data after sale

**Typical time to first probe:** early-game bottleneck is the 10000¤ cost (~200 ticks of income from a minimal economy); probes are a mid/late-game tool

### Colonization
1. **Claim:** dispatch a fleet to an unclaimed normal territory — fleet claims it on arrival, zero population
2. **Populate:** build and load a colony ship at any owned colonized territory (loads up to 100 unassigned pop), dispatch to the claimed territory — ship arrives and unloads population
3. Only after step 2 can facilities be built at the territory

**Colony ship travel time:** 1 node/tick (2h per node)

---

## Fleet Movement

- Fighters travel **2 nodes/tick** (4h per node)
- Pathfinding: BFS through passable tiles (own or unclaimed non-void); enemy tiles are valid targets but not transit corridors; void tiles are walls
- Fleet dispatch validates a reachable path exists before dispatching

### Fleet statuses
| Status | Meaning |
|---|---|
| `stationed` | At rest on a territory |
| `in_transit` | Traveling to destination |
| `pending_confirmation` | Arrived at enemy territory; 4-hour window before combat |
| `engaged` | In active combat this tick |
| `holding` | Present at enemy territory; not in combat |
| `occupying` | Last defender destroyed; 12-hour occupation window |
| `post_battle_choice` | Combat round resolved; 4-hour window to choose Rout/Raid/hold |
| `recalled` | Returning home |

---

## Combat

### Prerequisites
- War must be declared; 2-tick (4h) grace period before hostilities activate
- Fleet must arrive at enemy planet and pass the confirmation window

### Combat flow per tick

```
1. Fleet arrives at enemy planet → pending_confirmation (4h window)
   Attacker: confirm-attack or recall
   Defender: can see fleet size and expiry

2. Attacker confirms (or standing order = engage) → engaged

3. Combat fires (both sides simultaneously):
   net_damage = max(0, firing_count × FP − target_count × Shields)
   losses = max(1, round(net_damage / SI)) if net_damage > 0 else 0

   Home-territory bonus: defender_effective = defender_count × 1.5
   (applies only on defender's own colonized territory)

4a. Defender survives → post_battle_choice (4h window)
    Attacker chooses: Raid / Rout / hold
    Default (inaction) = hold

4b. Defender destroyed → occupying (12h window)
    Attacker chooses: Occupy (instant conquest) or Withdraw
    Default (inaction) = Withdraw

5. Attacker chooses engage next tick → repeat from step 3
   Attacker holds → holding (paying attrition, no combat)
```

### Damage formula
- **FP** (Firepower): 2 per starfighter
- **Shields**: 1 per starfighter (absorbs attacks below threshold entirely)
- **SI** (Structural Integrity): 5 per starfighter
- Both sides fire simultaneously; equal forces annihilate in ~2–3 ticks without home-territory bonus

### Post-battle choices (attacker)
| Choice | Effect |
|---|---|
| **Raid** | Steals resources scaled to fleet firepower; capped at `RAID_PRODUCTION_TICKS_CAP` (3) × territory's per-tick output per resource |
| **Rout** | Bonus damage: `int(defender_losses × 0.25)` extra defender losses |
| **Hold** | Fleet stays in `holding`; no combat this tick; pays attrition |

### Defender auto-rout (automatic, no player action)
When attacker takes more losses than defender AND attacker took nonzero losses: `bonus_attacker_losses = round(attacker_losses × DEFENDER_AUTO_ROUT_FRACTION)` (currently 0.50).

### Defender sortie (manual)
Defender can force any `holding` or `occupying` enemy fleet to `engaged`. Cooldown: once per 2 ticks (4h) per territory. If enemy is in `post_battle_choice`, sortie queues for next tick.

### Holding attrition
`max(1, round(unit_count × HOLDING_ATTRITION_RATE))` losses per tick (rate = 2.5%/tick). Only fires when the holding fleet's destination territory has a stationed enemy fleet (genuine contested occupation). A 100-unit fleet survives ~40 ticks (~80h) under attrition.

### Conquest (Occupy)
- Attacker in `occupying` executes `POST /fleets/{id}/occupy`
- Territory ownership transfers to attacker
- Territory dissent set to 60
- Fleet becomes stationed at the captured territory

---

## War System

| Event | Duration |
|---|---|
| War grace period (`war_pending`) | 2 ticks (4h) |
| Minimum war duration | 24h (12 ticks) |
| Post-peace redeclaration cooldown | Per `peace_until` on diplomacy row |
| Fleet confirmation window | 2 ticks (4h) |
| Post-battle choice window | 2 ticks (4h) |
| Occupation window | 6 ticks (12h) |

**Peace:** bilateral only — both nations must agree via the trade window. Can bundle resources, territories, and probe data alongside peace terms.

**Lopsided war:** if attacker military strength > 3× defender at declaration time, aggressor dissent accumulates at 1.5× rate (`DISSENT_LOPSIDED_MULTIPLIER`).

---

## Dissent

Per-territory integer 0–100. Sources and decay accumulate each tick.

| Source | Delta |
|---|---|
| Aggressor (declared war) | +3/tick all territories |
| Defender | +2/tick all territories |
| Holding/occupying fleet at territory | +6/tick |
| Engaged fleet at territory | +10/tick |
| Occupy action | Set to 60 |
| Peace (no occupation) | −3/tick |
| War, no occupation | −2/tick |
| Propaganda Office (normal) | +2 decay bonus |
| Propaganda Office (occupied) | +3 decay bonus |
| Propaganda Office (aggressor) | +1 decay bonus only |

**Production modifier:** `max(0, 1 − t^1.71)` where `t = max(0, (d−25)/75)`. No penalty below 25 dissent; 50% production loss at d=75; complete shutdown at d=100.

---

## Vacation Mode

| Rule | Value |
|---|---|
| Entry | Instant, no cooldown |
| Minimum stay | 48h |
| Exit aggression lockout | 48h (blocks fleet dispatch, colony ship dispatch, vacation re-entry) |
| While active | Untargetable; cannot dispatch fleets, collect resources, or act |
