# Nation Sim — Project Specification
*Working document. Update as decisions are made.*

---

## Vocabulary

- **Node** / **Territory** — interchangeable terms for a single point on the map. "Node" is preferred in technical/code contexts; "territory" is preferred in player-facing UI and game design writing.
- **Planet** — any node with non-zero resource richness (mineral_richness > 0 or fuel_richness > 0). Planets can be colonized and developed.
- **Void** — any node where both mineral_richness = 0 and fuel_richness = 0. Void nodes cannot be colonized or developed, but can be claimed (ownership established without population). Claimed void nodes are primarily relevant for trade route control and wartime blockades.
- **Anomaly** — a void-zone node with richness 5–10 in one resource and 0 in the other. Rare (1/1000 void hexes). Can be colonized.

---

## Concept Summary

A space-based browser nation simulator in the vein of CyberNations and Politics & War, differentiated by:
- A shared persistent world map with finite but expandable territory
- Player-driven exploration and colonization mechanics
- An information economy around probe/scout data
- Timer mechanics designed to not punish players for having a life

Possible name: "Interstellar States"

Players control space-based nations. Territory exists on a shared map. Conflict arises naturally from resource scarcity and territorial ambition rather than being purely consensual.

---

## Core Design Principles

**Inaction should never produce maximum harm.**
All timer-based events default to the safe outcome if the player is not present. Players can set contingency orders (e.g. "recall fleet if I don't confirm within X hours").

**The rim is a viable permanent playstyle, not a waiting room.**
Rim territory has lower resource density but lower conflict and lower maintenance costs. New players are not permanently disadvantaged by late entry.

**Exploration is a player archetype, not just a mechanic.**
Some players will specialize in exploration and information brokering rather than military or economic dominance. The systems should support this as a legitimate path.

**Complexity lives in the spreadsheet layer, not moment-to-moment gameplay.**
Actions are asynchronous and slow. Players queue actions and log out. The game should be engaging to think about between sessions, not require constant presence.

**Visible, engaged development is a feature.**
Maintain a public roadmap. Be responsive to the player community. This is a differentiator in the genre.

---

## World Structure

### Geography
- Single shared persistent map
- Space divided into clusters/solar systems
- Resource density increases toward the center of the map
- Rim territory: lower resources, lower conflict, viable for new/explorer players
- Core territory: highest resources, heavily contested, dominated by established players

### Territory States
- **Unclaimed/unexplored** — exists but unknown to players
- **Scouted** — a player has probe data; information is private unless sold
- **Claimed/colonized** — visible to all players on the map
- **Contested** — under active military pressure

### Map Expansion
- The map has a fixed initial size sufficient for alpha testing
- Procedural expansion triggered by player count or in-game events (TBD)
- Explored-but-undeveloped territory reverts to neutral after X days without maintenance to prevent squatting
- Territory holding costs scale to prevent monopolization by wealthy alliances

---

## Timer / Availability Design

The genre's central UX failure is punishing players for being offline. Mitigations:

| Problem | Solution |
|---|---|
| Fleet arrives and combat triggers while offline | Confirmation window (2 ticks / 4 hours); combat only triggers on confirm or window expiry |
| Can't step away during time-sensitive event | Vacation mode — instant entry, no entry cooldown; 48-hour minimum stay; 48-hour aggression lockout on exit; makes you untargetable but also unable to dispatch fleets or re-enter vacation |
| Missed timer = total loss | Soft damage model — gradual resource drain rather than single catastrophic strike |
| No control over offline fleet behavior | Standing orders — pre-set contingency actions (hold, recall, etc.) |
| Vacation mode used to block alliance war movement | Aggression lockout on exit prevents dispatching fleets for 48h after returning — a player who exits vacation to act as a territory blocker is exposed and unable to threaten for 48h. Long-term territorial blocking during extended vacation stays is a known open problem (see Open Questions). |

---

## Tech Stack

| Component | Choice | Status | Notes |
|---|---|---|---|
| Server | Bare metal home server (Xeon E3-1200, 16GB RAM, ~20TB free) | N/A (deployment) | Sufficient for closed beta |
| OS | CentOS Linux | N/A (deployment) | Familiar to developer |
| Containerization | Docker Compose | **Done** | All services defined with health checks |
| Database | PostgreSQL | **Done** | Service configured; full SQLAlchemy model layer with DBA-reviewed indexes |
| Backend | Python / FastAPI | **Done** | App skeleton, auth router, all ORM models |
| Task Queue | Celery + Redis | **Done** | Tick task runs every 2 hours; processes resource generation, population growth, fleet arrivals, colony ship arrivals |
| Frontend | React + Vite | **Done** | Scaffold, AuthContext, login/register pages, protected routing |
| Reverse Proxy | Nginx | **Done** | Config written, wired into Docker Compose |
| DNS / DDoS Protection | Cloudflare (free tier) | N/A (deployment) | Hides origin IP; handles SSL; DDoS mitigation |

### Container Layout (Approximate Resource Caps)
- PostgreSQL: ~4GB RAM
- Redis: ~1GB RAM
- FastAPI app: ~1GB RAM
- Celery worker: ~1GB RAM
- Nginx/frontend: minimal
- Remaining: media server + OS overhead

---

## What's Done

### Foundation
- Auth system: registration, login, sessions, password hashing, protected routes
- Nation creation flow
- UI skeleton with sidebar navigation
- Hex grid MapView with territory ownership display and fleet deployment workflow

### Economy
- Three resource types: minerals, fuel, population
- Tick system: Celery + Redis, 2-hour interval
- Resource generation per facility per tick:
  - Normal territory (richness 1–5): `max(5, round(richness × 2))` → 5–10/tick
  - Anomaly territory (richness 5–10): `round(richness × 2 + 10)` → 20–30/tick
- Construction system: mine, refinery, shipyard, probe factory
- Facility costs include currency (mine/refinery 500¤, shipyard 2000¤) to create a spending sink
- Population growth: 1%/tick, capped at `50 × (mineral_richness + fuel_richness)` per territory
- Currency income: 500¤/tick per colonized territory with at least one active mine or refinery
- Fleet currency upkeep: 2¤/tick per fighter regardless of status
- Fleet fuel upkeep: 1 fuel/tick per fighter not docked on an owned territory (in-transit, holding, pending, or stationed on foreign/unclaimed territory)
- Territory logistics upkeep: `k × N(N+1)/2` fuel/tick where N = owned territory count and k = `LOGISTICS_FUEL_K` (currently 1). The Nth territory costs N fuel/tick, making each additional territory more expensive than the last. Creates quadratic growth in costs while fuel income scales linearly, producing diminishing returns on territorial expansion. At k=1: 5 territories = 15 fuel/tick, 10 = 55 fuel/tick, 20 = 210 fuel/tick. **k is a balance knob — adjust based on beta feedback.**
- Event log page at `/log`: resource deltas, population changes, fleet events, combat, construction

### Exploration
- Probes: manufactured at probe factory (1000 min + 500 fuel + 10000¤ each), held in reserve, dispatched to destinations
- Probe range limited by distance from nearest owned colony
- Probe detection: territory owner notified on transit; probe destroyed if nations are at war
- Probe data (richness) recorded **only at the destination tile**; intermediate path tiles record `probe_visibility` (existence only, no richness)
- Probe recall: in-transit probes can be recalled from the Probes page; probe returns via shortest path and may be destroyed transiting enemy territory during war
- Probe intelligence auto-deleted when a territory is colonized (by claim or conquest) — colonized territories are visible to all, so the private data is moot
- Colony ships: built at shipyard (500 min + 1000 fuel each), hold up to 100 population, travel at 1 node/tick
- Colony ship load/unload at any owned colonized normal territory
- Territory claiming: a stationed fleet on an unclaimed normal territory claims it instantly; starts with zero population until a colony ship unloads
- Dynamic map generation: probes generate territory rows for uncharted hexes they scan; integer richness 1–5 weighted by distance from cluster center; void-zone anomalies at 1/1000 rate
- **Map fog of war**: the territory map only returns (a) claimed/colonized territories (visible to all per spec) and (b) `probe_visibility` tiles the player's probes have physically travelled through; richness values only shown for own territories and probe_data entries
- Probe data can be offered in the trade window: recipient sees richness and reachability (BFS from their territories) but **not coordinates**; `ProbeDataAccess` and `ProbeVisibility` granted on trade execution; probe data entries are also displayed in the "Your Intelligence" table on the Probes page

### Combat & Military
- Single unit type: starfighter (FP 2, Shields 1, Structural Integrity 5, 2 nodes/tick; costs 15 min + 30 fuel + 1000¤ each)
- Fleet movement: dispatch, in-transit travel, arrival landing with auto-merge into any existing stationed fleet of the same nation; dispatching defaults to the full fleet — specifying fewer units splits the fleet, leaving the remainder stationed
- Fleet pathfinding: dispatch validates reachability via BFS through passable (own/unclaimed, non-void) tiles; enemy tiles are dispatchable targets but not transit corridors; void tiles are impassable walls; en-route fleets do not auto-merge
- Vacation mode: instant entry, 48h minimum stay, 48h aggression lockout on exit, untargetable while active
- War declaration: 2-tick (4h) grace period before hostilities; blocked against vacation-mode targets; 24h minimum war duration
- Confirmation window: fleet entering enemy territory enters `pending_confirmation` for 2 ticks (4h); visible to both sides; attacker can confirm or recall; expiry executes standing order
- Standing orders: hold (default) or recall — applied on confirmation window expiry
- Combat damage model (shields): `net_damage = max(0, firing_count × FP − target_count × Shields)`; `losses = max(1, round(net_damage / Structural_Integrity)) if net_damage > 0 else 0`. Both sides fire simultaneously each tick. Shields absorb attacks below the threshold entirely. Implemented in `services/combat.py`, tested independently.
- Resource drain 5%/tick minerals + fuel when territory is undefended (engaged fleet, no defenders)
- Holding fleet attrition: `max(1, round(unit_count × 0.01))` losses per tick; fleet deleted at zero with event logged
- Territory conquest: an `engaged` fleet at an undefended enemy planet (no stationed defenders) can conquer via POST /fleets/{id}/conquer; ownership transfers to attacker, fleet stations at the captured territory; events logged for both attacker and defender
- Active Operations UI: Military page shows all non-stationed, non-in-transit fleets with contextual actions — `pending_confirmation` shows confirm-attack/recall and expiry timestamp; `engaged` at undefended territory shows Conquer/Recall; `engaged` with defenders shows In Combat/Recall; `holding` shows Recall

### Player Interaction
- Chat: public channels and direct messages with auto-tab on incoming DM
- Mail: inbox, outbox, delete
- Friends system: send/accept/refuse/cancel/remove requests; sidebar badge for incoming requests; friend_pending blocks fleet dispatch to that nation's planets
- Diplomacy statuses: neutral, war, war_pending, friendly, friend_pending
- Diplomatic name coloring: green (friendly/friend_pending), beige (neutral), red (war/war_pending) across map, probes, diplomacy, and friends pages
- Power metrics: military strength (1 per fighter, all statuses) and industrial strength (mine=1, refinery=1, shipyard=2, active only) — visible to all on nation profiles; visible to self on home page
- Territory rename cooldown: 24h (12 ticks); returns exact time remaining on 409
- Trading: two-player trades with 5-second two-click confirmation; trades can include any combination of resources (minerals, fuel, currency), one territory per side, multiple probe data entries per side, and/or a peace agreement to end a war; both parties must confirm; either can cancel/reject; incoming trade badge in sidebar
- **Bilateral peace only**: wars end exclusively via a mutually agreed peace trade; unilateral peace removed; proposer can bundle resources, territories, and probe data alongside peace terms
- Territory yield display: Planets page territory cards show per-territory production (minerals, fuel, net currency) in the card header alongside richness values

### Notifications & Events
- `territory_claimed` event includes `former_nation_id` in payload
- `territory_lost` event fires for the former owner when a territory changes hands

---

## New Mechanics

### Dissent System

Dissent is a per-territory integer (0–100) representing political unrest caused by military pressure. It degrades mineral and fuel production on a continuous curve. It decays over time and can be mitigated by the Propaganda Office facility. It does not punish inaction or offline play — it rises only because an enemy fleet is physically present or because the nation is actively at war.

---

#### Storage

New table, mirroring the pattern of `territory_population`:

```sql
CREATE TABLE territory_dissent (
    territory_id  INTEGER REFERENCES territories(id) PRIMARY KEY,
    dissent       INTEGER NOT NULL DEFAULT 0,
    last_updated  TIMESTAMPTZ DEFAULT NOW()
);
```

Only colonized territories get a row. Void nodes (no population) do not accumulate dissent.

---

#### What Raises Dissent (per tick)

| Trigger | Dissent added | Notes |
|---|---|---|
| Nation is at war — **aggressor** | +3 to **all** owned territories | Aggressor = the nation that declared war (`declared_by` on the diplomacy row) |
| Nation is at war — **defender** | +2 to **all** owned territories | Lower cost; the defender did not choose this war |
| Enemy fleet **holding** on this territory | +6 | Fleet committed but not yet in active combat |
| Enemy fleet **engaged** on this territory | +10 | Active combat or undefended occupation — same trigger whether defenders are present or not |
| Territory just conquered (changed hands) | Set to 60 instantly | Conquered populations start hostile |

Fleet-presence bonuses stack on top of the war-wide penalty. A defender's frontline territory under an engaged fleet accumulates +2 (war) + +10 (engaged) = +12/tick before decay.

**Hard rules:**
- Dissent is clamped to [0, 100].
- Dissent does not rise on vacation-mode nations — the tick is frozen for them, so no accumulation occurs.
- Dissent does not rise from the war declaration window or fleet dispatch alone. Only physically present enemy fleets and the war-state flag trigger dissent. This prevents declaration-and-recall harassment.
- Aggressor identity is recorded as `declared_by` on the `diplomacy` table row at declaration time and never mutated. It cannot be reclassified mid-war.

---

#### What Dissent Affects

**Production penalty** (minerals and fuel only; currency income is unaffected):

Continuous power curve. Below 25 dissent there is no effect. At 75 dissent exactly half of production is lost. At 100 dissent production is fully suppressed. The rate of loss accelerates as dissent rises.

```
t       = max(0, (d − 25) / 75)          # 0 at d=25, 1 at d=100
modifier = max(0.0, 1.0 − t ** n)        # n = ln(2)/ln(1.5) ≈ 1.71
```

The exponent `n ≈ 1.71` is derived from the anchor constraint modifier(75) = 0.5. It is stored as `DISSENT_CURVE_EXPONENT` in constants.py and can be tuned without changing the formula structure.

Reference values:

| Dissent | Modifier | Production loss |
|---|---|---|
| 0–25 | 1.00 | none |
| 50 | ≈ 0.85 | ~15% |
| 62 | ≈ 0.70 | ~30% |
| 75 | 0.50 | **50%** (anchor) |
| 87 | ≈ 0.28 | ~72% |
| 100 | 0.00 | complete |

**Population growth suppression:** deferred — not yet decided. Do not implement until the dissent production penalty has been tested in beta and the growth-suppression mechanic has been explicitly designed.

---

#### Decay (per tick)

| Condition | Base decay | With Propaganda Office |
|---|---|---|
| At peace, no enemy fleet | −3 | −5 |
| At war, no enemy fleet on this territory | −2 | −4 |
| Enemy fleet holding or engaged on this territory | 0 | −3 |

The Propaganda Office provides **+2 additional decay** at peace and at war without occupation, and **+3 additional decay** while enemy fleet is present (holding or engaged). The amplified bonus under occupation represents active local resistance; it slows the dissent rise but cannot halt it against a committed occupying force.

**Net balance examples:**

| Scenario | Net per tick |
|---|---|
| Defender, non-frontline, no office | +2 − 2 = **0** (stable) |
| Defender, non-frontline, with office | +2 − 4 = **−2** (slowly improving) |
| Aggressor, home territory, no office | +3 − 2 = **+1** (slow climb — war is costly at home) |
| Aggressor, home territory, with office | +3 − 4 = **−1** (stable with office) |
| Defender, engaged fleet, no office | +2 + 10 + 0 = **+12** (rapid rise) |
| Defender, engaged fleet, with office | +2 + 10 − 3 = **+9** (still rising, but slower) |

A planet at 100 dissent recovers to 0 in ~33 ticks (66 hours) at peacetime rate (−3/tick), or ~50 ticks (100 hours) at war rate (−2/tick), assuming no occupation.

---

#### Event Logging

Log an event to the events table only when dissent **crosses a threshold** (25, 50, 75, 100 — and back down through each). Do not log every tick delta. These correspond to the formula's onset point (25), ~11% loss (50), ~44% loss (75), and complete suppression (100). The threshold-crossing event fires a player-visible notification; the raw value is always available in the territory detail view.

---

#### Propaganda Office (New Facility)

One new facility that explicitly mitigates dissent. No other facilities get hidden morale bonuses.

| Field | Value |
|---|---|
| Type key | `propaganda_office` |
| Build cost | 500 minerals + 250 fuel + 6000¤ |
| Population required | 20 assigned |
| Effect | +2 additional dissent decay per tick on this territory |
| Limit | One per territory (enforced at endpoint level) |

Decay bonus: **+2/tick** normally; **+3/tick** while an enemy fleet is present (holding or engaged). The amplified bonus rewards defenders who invested in the facility pre-war.

| Condition | Base decay | With office |
|---|---|---|
| At peace | −3 | −5 |
| At war, no occupation | −2 | −4 |
| Under occupation | 0 | −3 |

---

#### Attacker-Side Dissent

Deferred to post-beta. The attacker currently does not accumulate dissent. If veteran feedback during beta indicates wars last too long with no internal political cost to the aggressor, add +2/tick to all attacker territories (same as the defender's war penalty) as a one-line change. See Open Questions.

---

## What's Still To Do

### Remaining Feature Work

**Exploration (Phase 3)**
- [ ] Information selling — probe data marketplace; players list and purchase others' probe data; seller retains data; UI shows data age and whether the target is already colonized at time of purchase

**Combat (Phase 4)**
- [ ] Pre-engagement skirmishing during `pending_confirmation` — small attrition losses each tick while fleet waits in the confirmation window (separate from holding fleet attrition, which is already implemented)
- [ ] Dissent system implementation — table, tick logic, production/growth penalties, decay, Propaganda Office facility, conquest-set behavior

**Player Interaction (Phase 5)**
- [ ] Probe data public marketplace — a listing board where players post probe data for sale at a fixed price; any nation can browse and purchase; seller retains data (already implemented for direct trade; public storefront is the remaining work)

**Alpha Test (Phase 6)**
- [ ] Invite veteran player testers (closed beta)
- [ ] Publish public roadmap
- [ ] Establish feedback collection process

### Known Open Issues

**Balance**
- **Population growth rate** — currently 1%/tick. Territories fill to their richness-based cap quickly at low populations. Monitor during beta; may need to reduce to 0.1–0.5% if population becomes a non-constraint too quickly.
- **Holding fleet attrition rate** — currently `max(1, round(unit_count × 0.01))` (1%/tick, min 1). A 100-unit fleet lasts ~100 ticks (~200 hours). Monitor during beta; reduce to 0.5% if fleets disappear before players can act, increase to 2% if lurking remains a problem.
- **Probes very expensive** - Exploration of new space is intended to be a later-game feature, players should first be trying to colonize territory that has already been discovered. On the other hand, what about once the original map has already been fully claimed, at what point should a new cluster be generated for new players to claim?

**Missing Standard Features**

---

## Post-Beta Roadmap

- Infrastructure maintenance costs (scaling to cap nation size ceiling)
- Resource transport / trade routes (supply chain)
- More unit types and combat depth
- Alliance mechanics (formal treaties, alliance banks, coordinated warfare)
- Espionage (steal probe data, sabotage infrastructure)
- Map expansion triggers
- Territory reversion / decay mechanics (anti-squatting)
- Vacation mode polish

---

## Open Questions

- **Dissent: attacker-side penalty?** Should the attacker also accumulate +2/tick dissent on their home territories for the duration of a war? Argument for: prolonged aggressive wars should have internal political cost. Argument against: in a 20–50 player beta, making aggression too costly reduces conflict below the threshold needed to test the war system. Recommendation: defer to post-beta unless veteran feedback says wars last too long.
- **Dissent: public or private?** Should a territory's dissent value be visible on the public nation profile? Public dissent creates interesting espionage-lite gameplay (attackers can see which planets are vulnerable) but lets third parties opportunistically pile on a nation already under pressure. Bring to veteran players.
- **Dissent: currency penalty?** The current design only penalizes mineral/fuel production, not currency income. If financially-focused players should feel war pressure more directly, add a currency multiplier at the same thresholds. Defer to beta feedback.
- **Dissent: population growth suppression?** Deferred by design decision. The production curve penalty is the primary mechanic. Whether high dissent should also suppress population growth (slowing the recovery of territory capacity after a war) has not been decided. Consider after beta: if players find wars leave no lasting mark once peace is reached and dissent decays, growth suppression is the lever to pull. If the production penalty alone is already punishing, leave it out.
- **Dissent on recapture/liberation:** If Nation A captures a planet from Nation B (dissent set to 60), and Nation B then retakes it, does dissent reset to 0 (liberation bonus) or continue from its current value? A reset rewards successful defense and is trivially implementable. Decide before territory conquest is implemented.
- **Dissent before conquest is implemented:** Dissent is useful as a pure combat-pressure mechanic (rising from holding/engaged fleets) even before territory conquest lands. The conquest-reset behavior (set to 60 on capture, reset on liberation) can be specified now and implemented alongside conquest.
Developer thoughts: Dissent should be raised for a planet when it specifically is beseiged, but maybe not for other planets when they are being attacked. Maybe more dissent for aggression wars and less for defense (requires creating a snapshot of original territory at war declaration).
- Population growth rate tuning and whether specific infrastructure types (beyond mines/refineries) should influence it.
- **Population cap range per territory**: the current cap is `50 × (mineral_richness + fuel_richness)`, giving a range of 50 (weakest planet, richness 1+0) to 500 (peak planet, richness 5+5). With facility density now driving currency income, low-richness planets are punished twice — less resource production AND a lower population cap limiting how many facilities can be staffed. Consider whether the cap formula should have a higher floor (e.g., a minimum cap regardless of richness) or a less steep slope so that rim planets can still staff a meaningful number of facilities.
- Whether colony vulnerability window (low population, low development) creates enough natural strategic depth or needs explicit mechanics.
- **Vacation mode as a territory blocker**: a player in vacation mode indefinitely still denies staging ground during alliance wars. The 48h lockout solves rapid in/out exploitation but not a committed long-term blocker. Possible solutions (not yet designed): war-declaration entry block; minimum fleet-presence requirement to invoke vacation; admin enforcement. Defer until beta feedback confirms whether this is a real problem in practice.
- **Defender repositioning during war declaration window**: when war is declared, both nations enter a 2-tick (4-hour) grace period before hostilities begin. During this window a defender who sees the `war_declared` notification can freely withdraw fleets, consolidate defenses, and reposition units — potentially negating any element of surprise and making offensive declarations weaker than intended. Possible mitigations: freeze fleet movement for both parties during the window; only restrict the attacker's fleet movement; apply a "mobilization" phase where both sides can reinforce but not reposition out of their own territory; limit the window to first-ever war declarations. No decision made — bring to veteran players during closed beta.
- **Occupation drain: what fraction of territory production should the attacker steal?** Currently the occupier drains 100% of the occupied territory's per-tick mineral and fuel output from the defender's stockpile, but the drained resources vanish (the attacker does not receive them). Two separate decisions: (1) What fraction of production is drained — 100% may make occupation so punishing that defenders prefer to sue for peace immediately, removing interesting mid-war decisions. A lower fraction (50%? 25%?) gives the defender more time to respond while still creating meaningful economic pressure. (2) Does the attacker receive the drained resources, or do they vanish? Receiving them makes conquest economically self-funding (CyberNations raiding model) which can incentivize aggressive warmongers. Vanishing them is pure denial pressure. Both have precedent. Decide before beta so conquest behavior is tunable without a model change.
- **Occupation drain: should drain scale with occupying fleet size?** Currently all fleet sizes drain identically — 1 fighter and 500 fighters drain the same territory production. Scaling with fleet size (e.g., `min(production, fleet_size × drain_per_unit)`) would make large occupation forces more threatening and give defenders a meaningful choice about whether to contest with a small garrison vs. concede. It would also make single-unit deep-strike raids (send 1 fighter far behind lines to drain a planet) less effective than a real occupation force. Downside: adds complexity and could disincentivize the small-garrison defender playstyle. Consider alongside the fraction decision above — the two parameters interact.
- **Territory count upkeep double-disadvantages rim players — monitor during beta.** The `k × N²` territory upkeep (k=10) creates a currency drain that scales with the number of territories owned, not their richness. Rim planets are already less economically productive (lower richness → fewer facilities → lower I per territory), which lowers their optimal empire size N*. The intended rim playstyle is a small, well-developed cluster used primarily as probe launch points for exploration income rather than raw resource production. If beta feedback shows rim players are squeezed out of viability by the combined effect of low facility income and territory count upkeep, consider: (a) flooring N² at a small constant for the first few territories, (b) reducing k, or (c) giving rim territories (distance_from_center above a threshold) a reduced upkeep weight in the formula. Do not change k without first observing actual beta expansion patterns.

---

## Decisions Log

| Question | Decision | Notes |
|---|---|---|
| Tick frequency | 2 hours | Standard for genre; revisit after beta feedback |
| Resources for beta | Minerals, Fuel, Population | Population staffs mines/refineries and is required for colony ships and combat units; grows organically over time, affected by infrastructure |
| Map size | 500–800 territory nodes | Supports 20–50 testers with room to expand before natural collision; revisit based on observed expansion rates |
| Probe data transfer | Non-exclusive | Seller retains data; UI shows data age and colonization status at time of purchase to mitigate scam potential |
| Confirmation window | 2 ticks (4 hours) | Consistent with game's internal logic; fleet holds visibly during window so defender can see it, call for help, and diplomacy can occur |
| Vacation mode mechanics | 48h minimum stay + aggression lockout on exit | 48-hour post-exit lockout blocks fleet dispatch, colony ship dispatch, and vacation re-entry. Surveyed CyberNations, P&W, OGame, Ikariam. Vacation entry history is public on player profile. |
| Colonization method | Two-step: fleet claims, colony ship populates | Fleets (starfighters) claim unclaimed territory on arrival; territory starts with zero population. Colony ships (500 minerals, 1000 fuel, 1 node/tick, 100 pop capacity) transfer population to enable facility construction and resource extraction. Probes cannot claim. |
| Shipyard design | Single facility builds both starfighters and colony ships | Costs 150 minerals + 60 fuel + 2000¤; requires 40 assigned population to operate. |
| Colony ship build cost | 500 minerals, 1000 fuel | No population cost at build time — colony ships are vessels, not population units. Population consumed only via the load action. Not subject to the general cost rebalance, to avoid blocking early colonization. |
| Territory income | 30 currency/tick per active mine or refinery | Scales with facility count per territory rather than a flat per-territory bonus. A territory with 1 mine earns 30¤/tick; one with 3 mines + 2 refineries earns 150¤/tick. Bare claimed territory generates zero currency. Rewards development depth over raw territory count. |
| Territory rename cooldown | 24 hours (12 ticks) | Prevents mid-war map confusion via rapid renames. Error response includes exact time remaining. |
| Map generation | Dynamic, probe-driven; integer richness 1–5 | Seeder creates full cluster + 6-hex void ring per cluster. Probes dynamically generate territory rows for uncharted hexes they scan. Richness weighted: 75% chance of 5 at cluster center, 75% chance of 1 at rim, linear slide. Void-zone hexes have 1/1000 chance of becoming an anomaly node (5–10 richness in one resource, 0 in the other). |
| Resource production scale | Normal 5–10/tick, anomaly 20–30/tick | Formula is territory-type-aware: normal `max(5, round(richness × 2))`; anomaly `round(richness × 2 + 10)`. Replaces flat `round(2 × richness)`. Closes the 5× rim/center gap and makes anomalies meaningfully more productive. |
| Resource cost rebalance | Tripled facility and fighter mineral/fuel costs; large currency costs added | Mine: 60 min + 30 fuel + 500¤. Refinery: 30 min + 60 fuel + 500¤. Shipyard: 150 min + 60 fuel + 2000¤. Fighter: 15 min + 30 fuel + 1000¤. Probe: 1000 min + 500 fuel + 10000¤. Colony ships unchanged. Rationale: slow expansion once the initial map is settled; currency costs create a meaningful spending sink that anchors the probe data marketplace. |
| Probe factory removed | Probe manufacture moved to shipyard; probe factory facility deleted | Probe factory was redundant given shipyard already handles all unit production. Shipyard now gates both fighter and probe manufacture. Removes a facility slot that provided no strategic decision — players had to build both a shipyard and a probe factory to field any military and explore. The 20-population cost of the probe factory is absorbed into the shipyard (already 40 population). |
| Holding fleet attrition | `max(1, round(unit_count × 0.01))` losses per tick | 1% attrition with minimum 1 unit/tick. Replaces the zero-cost lurking mechanic. Fleet deleted at 0 with events logged. Monitor rate during beta. |
| Fleet fuel upkeep | 1 fuel/tick per fighter not docked on own territory | "Docked" = stationed on a territory owned by that nation. All other fleet statuses and stationed fleets on foreign/unclaimed territory pay upkeep. Creates ongoing fuel drain for sustained military projection. |
| Power metrics | Military strength (1 per fighter) + industrial strength (mine=1, refinery=1, shipyard=2) | Computed at query time, not stored. Visible to all on nation profiles; visible to self on home page. Provides a competitive reference frame and a rough matchmaking signal. |
| Friends system | Separate from diplomacy; friend_pending blocks planet dispatch | Friend requests use the diplomacy table (status: friend_pending/friendly). A nation in friend_pending or friendly status cannot have fleets dispatched to their planets, treating them like neutral for combat purposes. |
| Dissent system | Per-territory integer 0–100; aggressor/defender asymmetry; fleet-presence penalties; Propaganda Office resistance; continuous production penalty curve | Sources: aggressor +3/tick all territories, defender +2/tick all territories, holding fleet +6, engaged fleet +10, instant set to 60 on conquest. Decay: −3 peace, −2 war (no occupation), 0 occupied. Propaganda Office: +2 decay normally, +3 under occupation. Production modifier: `max(0, 1 − t^1.71)` where `t = max(0, (d−25)/75)` — 50% loss at d=75, complete at d=100. Population growth suppression deferred. Notification events at thresholds 25/50/75/100. `declared_by` field on diplomacy row records aggressor. Does not rise during vacation mode. |
| Population consumption at fighter manufacture | Deducted from territory `current` population only; the richness-based cap (`50 × (mineral_richness + fuel_richness)`) is never modified | Population regrows naturally each tick toward the cap. Fighter deaths do not restore population — pop spent at manufacture is permanently gone if the unit is destroyed in combat. This resolves the open question "does population die permanently?" — yes, at the point of manufacture, but the territory's growth capacity is unaffected so the nation recovers over time. |
| Territory logistics upkeep | Quadratic fuel cost on territory count: `k × N(N+1)/2` fuel/tick, k=1 at beta start | Chosen to make empire growth logarithmic rather than linear: fuel income scales as N but logistics cost scales as N², creating a natural soft cap on expansion. The Nth territory costs N×k fuel/tick marginal cost. At k=1 a 20-territory empire pays 210 fuel/tick in logistics alone. k is stored as `LOGISTICS_FUEL_K` in constants.py and should be tuned during beta based on observed expansion rates. Do not change k without reviewing fuel production rates (5–10 fuel/tick per refinery on normal territories). |
| Territory count currency upkeep | Superlinear currency cost: `k × N²` per tick, k=10 at beta start | Marginal cost of the Nth territory = k(2N−1). Optimal expansion stops at N* ≈ I/(2k) where I = currency income per territory. At k=10: rim player (I≈150) optimal N*≈7, medium (I≈300) N*≈15, dense core (I≈600) N*≈30. Rewards deep development (higher I per territory → larger profitable empire) over pure sprawl. Creates the intended progression: develop territories to unlock the right to hold more of them. k stored as `TERRITORY_UPKEEP_K` in constants.py. See Open Questions for rim-player monitoring note. |
| Peace mechanic | Bilateral only — wars end exclusively through a mutually confirmed peace trade | Unilateral peace removed. Peace can be packaged with resource payments and territory transfers in the trade window, allowing structured negotiated settlements (reparations, cessions, white peace). The 24h minimum war duration does not apply to bilateral peace agreements. |
| Facility caps | Population is the only cap — stacking one facility type at the expense of others is a valid strategic choice; balance via population costs rather than hard slot limits. | |
| Combat damage model | Shields as flat damage reduction; `net_damage = max(0, firing × FP − target × Shields)`; `losses = max(1, round(net / Structural_Integrity)) if net > 0 else 0` | Both sides fire simultaneously. Unit stat names: FP, Shields, Structural_Integrity (formerly FP, DEF, HP). DEF was dead code; renamed to Shields and wired into formula. A well-shielded fleet fully absorbs weak attacks. |
| Probe visibility scope | Probe_data (richness) recorded only at the destination; all other tiles on the probe's path record probe_visibility (existence only) | Removes the radius-2 scanning behaviour that gave players richness data for tiles surrounding every step. The probe is a targeted instrument, not a scanner. Path tiles appear on the map as "tile exists" without stats. |
| Fleet dispatch default | Dispatch defaults to the full stationed fleet; entering fewer units splits the fleet, leaving the remainder stationed | The MapView quantity input defaults to max; shows "splits fleet" label and remaining-behind count when the user reduces it. Arriving fleets auto-merge into any existing stationed fleet at the destination. |

---

## Expert Review Notes

*Added 2026-05-29. Findings are grounded in code review of `backend/app/tasks/tick.py`, `backend/app/routers/military.py`, `backend/app/routers/diplomacy.py`, and `backend/app/constants.py` alongside the spec.*

---

### Best Practice Violations

**The `holding` fleet status conflates two distinct situations with incompatible mechanics.** A fleet enters `holding` when its confirmation window expires with `standing_order = "hold"`, and also when an `engaged` fleet's enemy territory becomes unowned or changes to a non-war state. Holding attrition (1%/tick) applies in all cases. This means a player who uses the default standing order after a ceasefire — or whose target territory changes hands mid-war — is silently paying 1%/tick with no contextual UI hint. The event log fires `holding_fleet_attrition` each tick but the Military page only shows "Recall" as the available action, giving no indication of why the fleet is holding or how fast it is decaying. OGame's fleet save culture produces exactly this failure mode: players who don't understand the system silently lose units while offline. Fix: surface attrition rate and projected time-to-zero in the Active Operations UI, and split `holding` into `holding_enemy` (attrition applies) and `holding_own_space` (no attrition) if staging on own space ever becomes a use case.

**~~Colony ship reachability is not enforced at the endpoint level.~~** *(Fixed — `send_colony_ship` now runs `compute_reachable_ids` before dispatch, identical to fleet dispatch.)*

**~~Population deduction for fighter manufacture draws from all territories in descending-population order, not from the shipyard territory.~~** *(Fixed — manufacture now deducts from the shipyard territory's population only, and fails if that territory has insufficient unassigned population.)*

**Specified:** Fighter manufacture consumes population from the territory on which the shipyard is built. The quantity produced is limited by that territory's unassigned population (territory current population minus population assigned to facilities at that territory). Population is permanently consumed — fighter deaths do not restore it.

**~~The `conquer_territory` endpoint deletes all probe data for the captured territory but does not delete probe visibility entries.~~** *(Fixed — `ProbeVisibility` rows are now deleted alongside `ProbeData` and `ProbeDataAccess` on conquest.)*

**War declaration allows fleets already in transit to proceed unimpeded through the 2-tick grace period.** When a war is declared, a `war_pending` row is created and hostilities begin 4 hours later. However, fleets dispatched before declaration (in status `in_transit`) continue to travel during the grace period and will arrive at the enemy territory the moment `war` becomes active, potentially before the defender has received a tick notification. The spec says the grace period exists so defenders can "see the war declared notification and prepare" — a fleet that departs the same tick war is declared can arrive the same tick war becomes active, negating the grace period entirely for short distances. This is the open question about "defender repositioning during war declaration window" from the Open Questions section and is flagged there, but the code has no guard against it.

---

### Missing Features

**No new player starting tutorial or guided first actions.** Veteran players testing a closed beta will orient themselves, but the starting state (100 minerals, 100 fuel, 2000¤, 100 pop, one territory) gives no in-game signal about what to build first. OGame and Ikariam both have guided first-action queues. Without this, early beta feedback will include confusion about the correct opening sequence (mine → shipyard → fighters vs. mine → probe factory → exploration), which is actually a meaningful strategic choice the game should surface, not obscure.

**~~No territory-level resource production breakdown accessible from the Military or Planets pages.~~** *(Partially fixed — the Planets page expanded panel now shows a Production / Tick section with per-territory gains (minerals, fuel, territory income) and costs (fighter upkeep), sourced from the existing `GET /api/nations/mine/territories/yields` endpoint. The Military page still does not show a per-territory breakdown of which territories are funding fleet upkeep; that cross-reference remains absent.)*

**~~No combat log accessible to third parties.~~** *(Fixed — `GET /api/nations/{nation_id}/wars` lists all wars for any nation (requires login), and `GET /api/nations/{nation_id}/wars/{opponent_id}/log` returns the full `combat_round` and `resources_drained_by_occupation` event history between any two nations, enriched with territory names. The public nation profile page now shows a "War History" section with a dropdown of past wars and "View Log →" links to a dedicated combat log page at `/nations/:id/wars/:opponentId`.)*

**No player-facing dissent UI.** The dissent system is fully specified and impacts production and population growth, but it is not yet implemented. When it does land, there is no existing UI surface for players to see their territories' current dissent levels, threshold-crossing notifications, or the effectiveness of Propaganda Offices. The event log threshold-crossing events (specified: log at 20, 40, 60, 80) need a dedicated display, and the territory detail view needs a dissent field. Plan this alongside dissent implementation, not after.

**No public probe data marketplace.** The direct-trade probe data transfer is implemented. The public storefront — where any nation can browse listed probe data, see richness and reachability without coordinates, and purchase at a seller-set price — is listed as remaining Phase 5 work. This is the primary mechanic enabling the exploration archetype as a standalone economy. Until it exists, explorer-type players can only transact via bilateral DMs, which requires social connection outside the game.

---

### Balance Issues

**Currency income is linear with territory count but fighter upkeep is linear with fighter count, creating a perverse incentive.** 500¤/tick per active territory, 2¤/tick per fighter. A 5-territory nation earns 2,500¤/tick and can sustain 1,250 fighters on currency alone before considering other costs. The logistics fuel cost (quadratic with territory count) constrains expansion via fuel, but currency has no equivalent brake. Infrastructure maintenance costs are post-beta — without them, large empires accumulate currency faster than small ones with no counterbalancing pressure. This means the dominant first-mover advantage is to colonize as many territories as possible early to build a currency surplus that sustains a fighter force small nations cannot match.

**Combat loss formula produces near-symmetrical attrition, making offensive war too costly.** With FP 2, Shields 1, SI 5, both attacker and defender lose `max(1, round((opponent × 2 - self × 1) / 5))` per tick when forces are roughly equal. Equal-sized forces annihilate each other in roughly 2–3 ticks. An attacker who travels several ticks to reach an enemy territory then fights to mutual destruction gains nothing — the territory is conquered with a badly depleted force that then immediately starts paying holding attrition. CyberNations used a ~3:1 attacker-to-defender ratio requirement to overcome ground defenses; P&W's resistance system means defenders absorb attacks without losing units until resistance hits zero. The current symmetric formula means conquest is only viable with overwhelming numerical superiority. The dissent system (when implemented) will add production pressure on both sides but does not change the fundamental combat exchange rate. A home-territory multiplier (e.g., defender effective count × 1.5) would make defense meaningful without changing the formula or unit stats.

**Holding fleet attrition applies equally regardless of which territory the fleet is holding at.** `holding` status applies both to fleets whose confirmation window expired at an enemy planet and to fleets that transition from `engaged` when a territory becomes uncontested. Attrition is 1%/tick in both cases. The spec says the default standing order is `hold` — a player who forgets to set `recall` loses 1%/tick silently until they check the event log. A 200-fighter fleet in holding at a friendly border (e.g., post-ceasefire, awaiting recall order) loses 2 fighters per tick, ~72 fighters in the 36 ticks of a weekend absence. The mechanic is correct for genuine occupation scenarios; it is punishing for fleets caught in limbo during war resolution. Consider only applying attrition to fleets holding on enemy-owned territory, not to fleets holding on unclaimed or formerly-enemy territory after ownership changes.

**~~Resource drain targets nation stockpile at a flat 5% regardless of attacker fleet size.~~** *(Fixed — drain is now bounded by the occupied territory's actual per-tick production. The occupier intercepts what the planet generates rather than raiding the national stockpile. A territory with no active facilities produces nothing to drain. See Open Questions for fraction and fleet-size scaling decisions.)*

**~~Demolish refund is 25% of mineral/fuel cost but does not refund currency.~~** *(Fixed — `tick.py` applies `DEMOLISH_REFUND_FRACTION` to all three resource components including currency. Mine demolish returns 125¤, refinery 125¤, shipyard 500¤.)*

---

> **WARNING — change these before exposing the server to the internet.**
> This file is tracked by git. Remove this section or rotate these values before pushing to a public repo or opening a port to the outside world.

| Variable | Value |
|---|---|
| `DB_PASSWORD` | `SpationDev2026` |
| `SECRET_KEY` | `CaoTU4MqP5BVyuXc6ktbjEL7dG1pZ9RDAgWfKIHln3mYsxeO` |

These are written to `.env` (git-ignored). To rotate: update `.env` and restart the stack. Rotating `SECRET_KEY` invalidates all existing sessions.

---

## Tutorial Planning

*Added 2026-06-01. Covers the first-session guided experience for closed beta players. The audience is veteran nation-sim players — they understand the genre. The tutorial's job is to surface this game's specific mechanics and ordering decisions, not to teach genre basics.*

---

### Learning Objectives

By the end of the tutorial sequence, a player should:

1. Know that population is a hard constraint on construction, not just a number to grow
2. Have a functioning production loop: minerals in, fuel in, currency accumulating
3. Understand that the shipyard gates all military and exploration actions
4. Have built at least one combat unit and understand its ongoing currency and fuel upkeep costs
5. Have dispatched and received a probe, and understand what probe data does and does not reveal (destination richness only — not path tile richness)
6. Have sent a colony ship to a scouted planet
7. Know that fleet dispatch to an owned territory claims it instantly; colony ship populates it
8. Have read the event log at least once and understand what it tracks

---

### Timing Baseline

Before designing gates, the real-time cost of each step must be understood. Assumptions: starting resources 100 min / 100 fuel / 2000¤ / 100 pop, rim home planet.

| Step | Resource cost | Build time | Notes |
|---|---|---|---|
| Mine | 60 min + 30 fuel + 500¤ + 10 pop | 1 tick (2h) | Can be queued immediately on game start |
| Refinery | 30 min + 60 fuel + 500¤ + 10 pop | 1 tick (2h) | Can be queued same session as mine if resources permit; needs 10 min + 10 fuel margin after mine |
| Shipyard | 150 min + 60 fuel + 2000¤ + 40 pop | 2 ticks (4h) | Currency bottleneck: mine+refinery together produce 60¤/tick, so ~17 ticks (~34h) needed from a 1000¤ balance after mine+refinery complete |
| Fighter | 15 min + 30 fuel + 1000¤ + 1 pop | Instant (manufactured) | 2¤/tick currency upkeep + 1 fuel/tick if not docked on own territory |
| Probe | 1000 min + 500 fuel + 10000¤ | Instant (manufactured) | Very expensive — intended as a later-game action; stockpiling is required |
| Colony ship | 500 min + 1000 fuel | Instant (manufactured) | No currency cost; no pop cost at build |

**The shipyard is the real first gate.** The currency gap (~34 hours from a typical starting position) is the dominant wait. Mine+refinery produce resources but currency drains from territory upkeep (`k × N²`), which at k=10 and N=1 is 10¤/tick — not enough to offset the 60¤/tick income from mine+refinery, so the net is +50¤/tick. From a 1000¤ starting balance after mine+refinery: need 1000 more¤ at +50¤/tick = 20 ticks = 40 hours. A new player who completes the first two buildings in their opening session and logs out will have the shipyard available on their second or third visit the next day. This is acceptable pacing for the genre.

**Probe is intentionally a late-game gate.** At 10000¤ cost and 50¤/tick net income from a one-planet economy, a new player needs ~200 ticks (~400 hours) of income just for a single probe if they save every¤. This is wrong for a tutorial. Probes are not a new-player mechanic — the map already has terrain generated by seeding, so players can expand into pre-seeded territory using fleets (which claim unclaimed territory on arrival) without needing probes. The tutorial should deprioritize probes relative to the proposed flow. See recommendation below.

---

### The 90% Population Utilization Gate: Do Not Use

The proposed trigger — "once planet reaches 90% population utilization, create a probe" — has two fatal problems:

**Problem 1: The gate may be impossible to hit on a richness-1 home planet.** Pop cap = 50 × (mineral_richness + fuel_richness). A planet with richness 1+1 has a cap of 100, and the player starts with exactly 100 pop — already at cap. Growth rate is 1%/tick of current population, capped. No growth ever occurs. Assigned pop after mine + refinery + shipyard = 10 + 10 + 40 = 60 pop = 60% utilization. Reaching 90% requires 30 more pop in facilities (3 more mines/refineries/propaganda offices), but the population never grows to enable that — it is already at cap. The gate is never triggered.

**Problem 2: Even on a higher-richness planet, the time required is prohibitive.** On a 2+2 planet (cap 200), population grows from 100 at 1%/tick. To reach 180 pop (90% of 200) takes ~59 ticks (~118 hours, roughly 5 days), assuming facilities keep pace with population. For a tutorial prompt, five days of real time before the colonization step is not a delay — it is abandonment.

**Recommendation: replace this gate entirely.** Use a shipyard completion event as the trigger for the fighter and probe/colonization steps. The tutorial prompt fires when the first shipyard completes, not when a population threshold is met.

---

### Recommended Tutorial Flow

The tutorial is a sidebar task list tied to game state — not a forced linear path and not an overlay. Prompts appear when conditions are met; the player can dismiss the tutorial entirely at any time. Steps are numbered to show the expected ordering. Steps marked **[implemented]** are live; the rest are planned for a future pass.

**Step 1 — Build a mine** (triggers on: nation creation) **[implemented]**

Prompt: "Your home planet generates minerals passively each tick. Build a mine to extract them. Minerals are your primary construction resource." Show cost, pop requirement, build time. Teach: resource deduction is immediate; facility takes 1 tick to activate.

Reward: +500 minerals, +500 currency — awarded immediately when the build is queued, not at tick completion.

**Step 2 — Build a refinery** (triggers on: mine queued or active) **[implemented]**

Prompt: "Refineries extract fuel — required for fleet movement, probes, and colony ships. Build one now while the mine completes." Teach: parallel construction is intentional; fuel is distinct from minerals; both are needed before any fleet can move far.

Reward: +500 fuel, +500 currency — awarded immediately when the build is queued.

**Step 3 — Review planet production** (triggers on: player visits the Planets page while on step 3) **[implemented]**

Prompt: "Visit the Planets tab to see your resource gain and loss rates." The production section on the Planets page is highlighted with an amber outline while this step is active. Completing this step requires no player action beyond navigating to /planets — it auto-completes on visit. Teach: currency income per tick, territory upkeep, the development-depth-over-sprawl principle.

Reward: +100 minerals, +100 fuel, +500 currency — awarded immediately when the player visits the Planets page.

**Step 4 — Build a shipyard** (triggers on: at least one mine and one refinery active, sufficient resources) **[implemented]**

Prompt: "The shipyard is required to build fighters, colony ships, and probes. It costs 2000¤ and takes 2 ticks to complete. Begin construction when you have the resources — income from your mine and refinery will get you there." Teach: the shipyard is the progression gate; 2-tick build time means planning ahead; the player should understand they are waiting for income, not doing something wrong.

Reward: +1000 currency (half the shipyard cost) — awarded at tick time when the shipyard completes, not on queue.

**Step 5 — Manufacture a fighter** (triggers on: shipyard becomes active)

Prompt: "Your shipyard is ready. Manufacture a fighter — your first military unit. Fighters have an ongoing currency upkeep cost of 2¤/tick and 1 fuel/tick when deployed away from home. A small standing garrison protects against opportunistic claims. Check the Military page to deploy it." Teach: upkeep exists and is ongoing; a single fighter stationed at home is cheap insurance; the Military page is where fleet management lives; fighters have stats (FP, Shields, SI) that matter in combat.

**Step 6 — Review the event log** (triggers on: fighter manufactured)

Prompt: "Open the Log page. Every tick generates entries: resource production, population changes, fleet status, and construction completions. This is your primary tool for understanding what happened while you were offline." Teach: the game is asynchronous; players should check the log after returning; teach what each entry type means.

**Step 7 — Understand the map and fleet dispatch** (triggers on: at least one fighter stationed; completes on: fleet dispatched to any node other than current location)

Prompt: "From the Map, you can dispatch your fleet to any reachable node. Fleets travel at 2 nodes per tick. Dispatching to an unclaimed node claims it on arrival. Void nodes cannot be colonized or developed, but can be claimed to control trade routes. Dispatching to an enemy planet enters a 4-hour confirmation window before combat can occur." Teach: map fog-of-war basics; fleet pathfinding rules; the difference between planets and void nodes; the confirmation window and standing orders (hold/recall); that claiming is separate from colonizing.

**Step 8 — Build and send a colony ship** (triggers on: have at least 1 claimed territory with known richness, have 100+ unassigned pop, have a shipyard)

Prompt: "Claimed territory is owned but empty — no facilities can be built until population arrives. A colony ship loads up to 100 population from any colonized planet you own and carries it to a claimed planet. Build one at your shipyard. Colony ships travel 1 node per tick — slower than fighters." Teach: the two-step claim/colonize distinction; colony ship load/unload mechanics; slower speed than fighters; requires 100 unassigned pop at the source planet.

**Step 9 — Scout with a probe** (triggers on: colony ship manufactured)

Prompt: "When nearby space is claimed or too contested to expand into safely, probes let you scout further out. A probe reveals the resource richness of its destination — giving you intelligence before you commit a colony ship. Probe range is 10 nodes from your nearest colony. Data is destination-only (not along the path) and can be sold to other players. Build a probe at your shipyard when resources allow." Teach: probes are a tool for finding expansion opportunities beyond the contested frontier, not a prerequisite for all colonization; probe cost; range limitation; data is destination-only; the information economy exists; probe data is non-exclusive on sale.

**Step 10 — Tutorial complete** (triggers on: second planet colonized)

Prompt: "You have a functioning multi-planet empire. The rest of the game is yours — expand, develop, trade, or pick a fight. Check the Diplomacy page to see who your neighbors are. Use the event log and the nation profiles page to track the competitive landscape." Point to remaining game systems without prescribing a path.

---

### What the Original Proposal Got Right and Wrong

**Good:** Mine before refinery before shipyard is the correct ordering. Both resources are needed before the shipyard can be queued. This sequence was kept as steps 1, 2, and 4.

**Fixed — fighter before colonization:** The original proposal put fighter creation before probing and colonization, implying combat was the next step after infrastructure. The implemented flow introduces the fighter at step 5 as "defense basics" alongside shipyard completion, without making it a gate on the colonization path.

**Fixed — probe before colony ship:** The original proposal had probing before the colony ship step. This was reversed: colony ship is step 8, probe is step 9. The seeded map gives new players nearby claimable territory without needing probes; probing is taught as the tool for pushing beyond the pre-seeded zone.

**Fixed — 90% population utilization gate:** The original proposal used 90% population utilization as the trigger for the probe/colonization steps. This gate is unachievable on a richness-1+1 home planet (pop starts at cap, never grows) and requires ~5 real days on higher-richness planets. Replaced with facility-completion gates throughout.

**Added — immediate rewards for steps 1 and 2:** Steps 1 (mine) and 2 (refinery) award resources the moment the player queues construction, not at tick completion. This provides immediate gratification during the first session rather than making new players wait 2 hours to see any feedback. Step 4 (shipyard) rewards at tick time — the wait is intentional there as part of the progression pacing.

**Added — step 3 as Planets page orientation:** The original proposal had no UI orientation step. Step 3 directs the player to the Planets tab and highlights the production section with an amber outline while the step is active. It auto-completes on page visit. This teaches currency income and upkeep at the moment those numbers first become visible.

**Still missing (steps 5–10 not yet implemented):** Event log step, map/fleet dispatch step with confirmation window explanation, colony ship step, probe step, and tutorial complete state. These will be implemented in a future pass.

---

### Gating Logic Summary

| Tutorial step | Gate condition | Real-time estimate |
|---|---|---|
| Build mine | Nation created | Day 1, first session |
| Build refinery | Mine queued or active | Day 1, first session |
| Understand currency | First mine or refinery active | Day 1, 2h in |
| Build shipyard | Mine + refinery active | Day 1–2 (currency accumulation, ~40h) |
| Manufacture fighter | Shipyard active | Day 2 or 3 |
| Read event log | Fighter manufactured | Day 2 or 3 |
| Fleet dispatch / map | Fighter stationed | Day 2 or 3 |
| Colony ship | Claimed territory + 100 pop available | Day 3–5 |
| Send probe | Colony ship manufactured | Day 3–5 |
| Tutorial complete | Second territory colonized | Day 3–5 |

---

### Open Questions for Tutorial Design

- **Prompt format:** ~~Tooltip overlay, sidebar task list, or notification inbox?~~ **Resolved: sidebar task list.** Implemented as a persistent panel in the left nav sidebar, consistent with OGame's Advisor pattern. Overlays were rejected because they require the player to be online at the trigger moment.
- **Skip/dismiss:** ~~Can veteran players dismiss the tutorial?~~ **Resolved: yes.** A "Skip tutorial" button is present in the sidebar panel and sets `dismissed = true` immediately. No re-enable option in the current implementation; can be added if beta feedback requests it.
- **Starting currency:** Current 2000¤ start produces a ~40h wait for the shipyard at +50¤/tick net income. This may be acceptable for veterans but will be a dropout point for general players. Consider raising to 4000–5000¤ before beta launch. Monitor first-session completion rates.
- **Home planet richness assignment:** The tutorial timing analysis assumes the home planet can have a pop cap above the starting 100 pop. If players pick a richness-1+1 planet (cap exactly 100), population never grows, and any growth-based tutorial gate fails. Either enforce a minimum home planet richness (e.g., mineral_richness + fuel_richness >= 4) at nation creation, or ensure no tutorial step uses population growth as a gate. The revised flow above avoids growth-based gates entirely, but the minimum richness question should be decided regardless for game balance reasons.
- **Probe tutorial timing:** Probes cost 10000¤ and 1000 min + 500 fuel. A single-planet economy running mine + refinery generates ~50¤/tick net and 5 min + 5 fuel/tick. Reaching probe cost from tutorial-complete state takes approximately 200 ticks for currency alone. This is by design (probes are a later-game tool), but the tutorial should set this expectation explicitly rather than implying probes are a near-term goal. The step 9 prompt as written does this.
- **Step 9 completion gate:** Should step 9 require the player to actually build and dispatch a probe to complete, or does the tutorial complete on colony ship manufacture (when the prompt appears)? Requiring a probe dispatch gives a stronger "done it once" confirmation but the cost (~200 ticks of savings) means most new players will not complete step 9 quickly. Consider whether an incomplete tutorial is worse than a tutorial that takes weeks to finish.

Fix 1 — DEF as 1.5× garrison multiplier: don't implement as described
The intent is right but the hook is wrong. Wiring the DEF stat now creates two overlapping sources of the same effect once stationary defenses arrive — you'd have to untangle them later. Instead, implement the home-territory advantage as a separate explicit multiplier on the defender's effective count (defender_effective = count × 1.5 if on own territory). This achieves the same balance result today, stays structurally separate from whatever DEF eventually does, and stationary defenses can be added independently without interference. Leave DEF=1 in the constants as a stub signaling that differentiation is coming.

Fix 2 — uniform(0.3, 0.5) randomness: holds up cleanly
One change: draw the random coefficient once per tick per engagement, not per unit type. When multiple unit types exist, independent draws per type create weird cross-type interactions that look like bugs. Single draw, applied uniformly to the engagement.

Fix 3 — 2.0× first-contact fortification bonus: lower it to 1.5× and scope it to mobile units only
Stationary defenses are "always first contact" by definition — they're permanent emplacements. If you apply a 2.0× first-contact multiplier to all defenders including stationary defenses, the first tick of attacking a defended planet becomes impenetrable. The fix: first-contact bonus is 1.5× on mobile defenders only on tick 1. Stationary defenses get no bonus multiplier — their strength comes from their dedicated firepower, not a transient bonus.

The bigger structural question: how stationary defenses integrate
This is the most important forward-compatibility decision. Three options:

A. Pooled with mobile units — stationary defenses add to the defender's count aggregate. Simple, but requires modeling how they degrade, get repaired, survive conquest, etc. Also blurs the combat log ("did the garrison hold or did the guns?").

B. Pre-engagement phase (recommended — Ikariam model) — stationary defenses fire first, inflicting attacker losses before mobile combat begins. No defender losses in this phase. Then surviving attackers fight the stationed fleet. This separates tuning for stationary defenses from mobile unit balance entirely, and maps cleanly to the dissent system (a territory saved by its garrison vs. its cannons feels politically different).

C. Flat territory modifier — same stacking problem as the DEF multiplier issue above.

The expert recommends Option B. The formula structure becomes:

Stationary defense phase: attacker takes losses from fixed installations, no defender losses
Mobile combat phase: surviving attackers fight the stationed fleet
Multi-tier unit types and targeting priority
The previous recommendation was to skip targeting priority entirely. That's partially revised:

If you adopt the phase model above, targeting is handled by the phase structure — attackers can't bypass stationary defenses, they always fire first
When multi-tier mobile combat arrives, distribute losses proportionally across unit types (not selective targeting). This avoids the CyberNations exploit where players brought cheap units as loss sponges because damage was assigned to the cheapest units first
Explicit player-selectable targeting priority can still be deferred — the phase structure handles it implicitly
What to actually implement now vs. defer
Implement now (small code changes to tick.py):

uniform(0.3, 0.5) drawn once per engagement per tick
1.5× home-territory multiplier as an explicit multiplier, not through DEF
First-contact bonus at 1.5× (not 2.0×), mobile defenders only
Add as a no-op stub now:

calculate_stationary_defense_losses(territory_id, attacker_count) → int returning 0, called before the mobile combat phase. When stationary defenses ship you fill in the stub — the main combat loop never needs refactoring.
Decisions to record in the spec:

Stationary defenses use pre-engagement phase model (fires before mobile combat, no defender losses in that phase)
First-contact bonus is 1.5× on mobile defenders only on tick 1
Multi-tier loss distribution is proportional across unit types, not selective
Targeting priority deferred pending multi-tier beta feedback