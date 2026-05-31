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
- Single unit type: starfighter (ATK 2, Shields 1, Structural Integrity 5, 2 nodes/tick; costs 15 min + 30 fuel + 1000¤ each)
- Fleet movement: dispatch, in-transit travel, arrival landing with auto-merge into any existing stationed fleet of the same nation; dispatching defaults to the full fleet — specifying fewer units splits the fleet, leaving the remainder stationed
- Fleet pathfinding: dispatch validates reachability via BFS through passable (own/unclaimed, non-void) tiles; enemy tiles are dispatchable targets but not transit corridors; void tiles are impassable walls; en-route fleets do not auto-merge
- Vacation mode: instant entry, 48h minimum stay, 48h aggression lockout on exit, untargetable while active
- War declaration: 2-tick (4h) grace period before hostilities; blocked against vacation-mode targets; 24h minimum war duration
- Confirmation window: fleet entering enemy territory enters `pending_confirmation` for 2 ticks (4h); visible to both sides; attacker can confirm or recall; expiry executes standing order
- Standing orders: hold (default) or recall — applied on confirmation window expiry
- Combat damage model (shields): `net_damage = max(0, firing_count × ATK − target_count × Shields)`; `losses = max(1, round(net_damage / Structural_Integrity)) if net_damage > 0 else 0`. Both sides fire simultaneously each tick. Shields absorb attacks below the threshold entirely. Implemented in `services/combat.py`, tested independently.
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

Dissent is a per-territory integer (0–100) representing political unrest caused by military pressure. It degrades production and suppresses population growth. It decays over time and can be mitigated by a new facility. It does not punish inaction or offline play — it rises only because an enemy fleet is physically present or because the nation is actively at war.

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
| Nation is at war | +2 to **all** owned territories | War-wide cost; unavoidable while at war |
| Enemy fleet holding on this territory | +5 | Replaces (does not stack with) the engaged bonus |
| Enemy fleet engaged on this territory | +8 | Active battle zone |
| Territory undefended and actively being resource-drained | +10 | Looting is directly felt by the population |
| Territory just conquered (changed hands) | Set to 60 instantly | Conquered populations start hostile |

**Hard rules:**
- Dissent is clamped to [0, 100].
- Dissent does not rise on vacation-mode nations — the tick is frozen for them, so no accumulation occurs.
- Dissent does not rise from the war declaration window or fleet dispatch alone. Only physically present enemy fleets and the war-state flag trigger dissent. This prevents declaration-and-recall harassment.

---

#### What Dissent Affects

**Production penalty** (minerals and fuel only; currency income is unaffected):

| Dissent | Production multiplier |
|---|---|
| 0–19 | 1.00 — no effect |
| 20–39 | 0.90 — 10% reduction (grumbling) |
| 40–59 | 0.75 — 25% reduction (unrest) |
| 60–79 | 0.55 — 45% reduction (protest) |
| 80–100 | 0.30 — 70% reduction (revolt) |

**Population growth suppression:**

| Dissent | Growth effect |
|---|---|
| 0–39 | Unaffected |
| 40–59 | Growth rate halved |
| 60–100 | Growth rate zeroed (not negative — population does not flee or die) |

---

#### Decay (per tick)

| Condition | Decay per tick |
|---|---|
| At peace, no enemy fleet | −3 |
| At war, no enemy fleet on this territory | −1 |
| Enemy fleet holding or engaged on this territory | 0 (no decay) |

At war with no enemy fleet present, non-frontline territories accumulate a net **+1 dissent/tick** (+2 war penalty − 1 decay). A Settlement Hub raises decay to −3, producing a net −1/tick and keeping non-frontline territories stable during a prolonged war. Front-line planets under occupation continue to climb. A planet maxed at 100 dissent recovers to 0 in ~33 ticks (66 hours) at peacetime rate, or ~100 ticks at war rate without a hub (no occupation).

---

#### Event Logging

Log an event to the events table only when dissent **crosses a threshold** (20, 40, 60, 80 — and back down through each). Do not log every tick delta. The threshold-crossing event fires a player-visible notification; the raw value is always available in the territory detail view.

---

#### Settlement Hub (New Facility)

One new facility that explicitly mitigates dissent. No other facilities get hidden morale bonuses.

| Field | Value |
|---|---|
| Type key | `settlement_hub` |
| Build cost | 200 minerals + 100 fuel + 3000¤ |
| Population required | 20 assigned |
| Effect | +2 additional dissent decay per tick on this territory |
| Limit | One per territory (enforced at endpoint level) |

Combined decay with a Settlement Hub:

| Condition | Decay per tick |
|---|---|
| At peace + hub | −5 |
| At war, no occupation + hub | −3 (exactly cancels the +2/tick war penalty — hub keeps a non-frontline planet stable) |
| Under occupation + hub | −2 (insufficient to offset +5/+8 occupation; hub slows the rise but does not halt it) |

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
- [ ] Dissent system implementation — table, tick logic, production/growth penalties, decay, Settlement Hub facility, conquest-set behavior

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

**Implementation Gaps**
- **Probes can silently strand mid-transit** — if `_next_step()` resolves to a hex not yet generated, the probe stops moving with no event, no notification, and no recovery. Affects probe paths through ungenerated space.
- **Colony ship reachability not enforced** — ships can be dispatched across the entire map with no adjacency or path check, bypassing the flanking/leapfrog design intent. The spec requires ships to travel through owned or reachable space; the endpoint does not verify this.

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
- **Dissent on recapture/liberation:** If Nation A captures a planet from Nation B (dissent set to 60), and Nation B then retakes it, does dissent reset to 0 (liberation bonus) or continue from its current value? A reset rewards successful defense and is trivially implementable. Decide before territory conquest is implemented.
- **Dissent before conquest is implemented:** Dissent is useful as a pure combat-pressure mechanic (rising from holding/engaged fleets) even before territory conquest lands. The conquest-reset behavior (set to 60 on capture, reset on liberation) can be specified now and implemented alongside conquest.
Developer thoughts: Dissent should be raised for a planet when it specifically is beseiged, but maybe not for other planets when they are being attacked. Maybe more dissent for aggression wars and less for defense (requires creating a snapshot of original territory at war declaration).
- Population growth rate tuning and whether specific infrastructure types (beyond mines/refineries) should influence it.
- Whether colony vulnerability window (low population, low development) creates enough natural strategic depth or needs explicit mechanics.
- **Vacation mode as a territory blocker**: a player in vacation mode indefinitely still denies staging ground during alliance wars. The 48h lockout solves rapid in/out exploitation but not a committed long-term blocker. Possible solutions (not yet designed): war-declaration entry block; minimum fleet-presence requirement to invoke vacation; admin enforcement. Defer until beta feedback confirms whether this is a real problem in practice.
- **Defender repositioning during war declaration window**: when war is declared, both nations enter a 2-tick (4-hour) grace period before hostilities begin. During this window a defender who sees the `war_declared` notification can freely withdraw fleets, consolidate defenses, and reposition units — potentially negating any element of surprise and making offensive declarations weaker than intended. Possible mitigations: freeze fleet movement for both parties during the window; only restrict the attacker's fleet movement; apply a "mobilization" phase where both sides can reinforce but not reposition out of their own territory; limit the window to first-ever war declarations. No decision made — bring to veteran players during closed beta.

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
| Territory income | 500 currency/tick per colonized territory with ≥1 active mine or refinery | Bare claimed territory generates zero currency. Keeps development meaningful. |
| Territory rename cooldown | 24 hours (12 ticks) | Prevents mid-war map confusion via rapid renames. Error response includes exact time remaining. |
| Map generation | Dynamic, probe-driven; integer richness 1–5 | Seeder creates full cluster + 6-hex void ring per cluster. Probes dynamically generate territory rows for uncharted hexes they scan. Richness weighted: 75% chance of 5 at cluster center, 75% chance of 1 at rim, linear slide. Void-zone hexes have 1/1000 chance of becoming an anomaly node (5–10 richness in one resource, 0 in the other). |
| Resource production scale | Normal 5–10/tick, anomaly 20–30/tick | Formula is territory-type-aware: normal `max(5, round(richness × 2))`; anomaly `round(richness × 2 + 10)`. Replaces flat `round(2 × richness)`. Closes the 5× rim/center gap and makes anomalies meaningfully more productive. |
| Resource cost rebalance | Tripled facility and fighter mineral/fuel costs; large currency costs added | Mine: 60 min + 30 fuel + 500¤. Refinery: 30 min + 60 fuel + 500¤. Shipyard: 150 min + 60 fuel + 2000¤. Probe factory: 30 min + 15 fuel. Fighter: 15 min + 30 fuel + 1000¤. Probe: 1000 min + 500 fuel + 10000¤. Colony ships unchanged. Rationale: slow expansion once the initial map is settled; currency costs create a meaningful spending sink that anchors the probe data marketplace. |
| Holding fleet attrition | `max(1, round(unit_count × 0.01))` losses per tick | 1% attrition with minimum 1 unit/tick. Replaces the zero-cost lurking mechanic. Fleet deleted at 0 with events logged. Monitor rate during beta. |
| Fleet fuel upkeep | 1 fuel/tick per fighter not docked on own territory | "Docked" = stationed on a territory owned by that nation. All other fleet statuses and stationed fleets on foreign/unclaimed territory pay upkeep. Creates ongoing fuel drain for sustained military projection. |
| Power metrics | Military strength (1 per fighter) + industrial strength (mine=1, refinery=1, shipyard=2) | Computed at query time, not stored. Visible to all on nation profiles; visible to self on home page. Provides a competitive reference frame and a rough matchmaking signal. |
| Friends system | Separate from diplomacy; friend_pending blocks planet dispatch | Friend requests use the diplomacy table (status: friend_pending/friendly). A nation in friend_pending or friendly status cannot have fleets dispatched to their planets, treating them like neutral for combat purposes. |
| Dissent system | Per-territory integer 0–100; rises from war and enemy fleet presence; decays over time; penalizes production and population growth | Sources: +2/tick (at war, all territories), +5 (holding fleet), +8 (engaged fleet), +10 (actively drained), instant set to 60 (conquest). Decay: −3/tick (peace), −1/tick (war, no occupation), 0 (occupied). Production multiplier at 5 thresholds (1.00 → 0.30). Growth suppression at 40+ and zeroed at 60+. Settlement Hub facility (+2 decay/tick, one per territory). Attacker-side dissent deferred to post-beta. Does not rise during vacation mode. |
| Population consumption at fighter manufacture | Deducted from territory `current` population only; the richness-based cap (`50 × (mineral_richness + fuel_richness)`) is never modified | Population regrows naturally each tick toward the cap. Fighter deaths do not restore population — pop spent at manufacture is permanently gone if the unit is destroyed in combat. This resolves the open question "does population die permanently?" — yes, at the point of manufacture, but the territory's growth capacity is unaffected so the nation recovers over time. |
| Territory logistics upkeep | Quadratic fuel cost on territory count: `k × N(N+1)/2` fuel/tick, k=1 at beta start | Chosen to make empire growth logarithmic rather than linear: fuel income scales as N but logistics cost scales as N², creating a natural soft cap on expansion. The Nth territory costs N×k fuel/tick marginal cost. At k=1 a 20-territory empire pays 210 fuel/tick in logistics alone. k is stored as `LOGISTICS_FUEL_K` in constants.py and should be tuned during beta based on observed expansion rates. Do not change k without reviewing fuel production rates (5–10 fuel/tick per refinery on normal territories). |
| Peace mechanic | Bilateral only — wars end exclusively through a mutually confirmed peace trade | Unilateral peace removed. Peace can be packaged with resource payments and territory transfers in the trade window, allowing structured negotiated settlements (reparations, cessions, white peace). The 24h minimum war duration does not apply to bilateral peace agreements. |
| Facility caps | Population is the only cap — stacking one facility type at the expense of others is a valid strategic choice; balance via population costs rather than hard slot limits. | |
| Combat damage model | Shields as flat damage reduction; `net_damage = max(0, firing × ATK − target × Shields)`; `losses = max(1, round(net / Structural_Integrity)) if net > 0 else 0` | Both sides fire simultaneously. Unit stat names: ATK, Shields, Structural_Integrity (formerly ATK, DEF, HP). DEF was dead code; renamed to Shields and wired into formula. A well-shielded fleet fully absorbs weak attacks. |
| Probe visibility scope | Probe_data (richness) recorded only at the destination; all other tiles on the probe's path record probe_visibility (existence only) | Removes the radius-2 scanning behaviour that gave players richness data for tiles surrounding every step. The probe is a targeted instrument, not a scanner. Path tiles appear on the map as "tile exists" without stats. |
| Fleet dispatch default | Dispatch defaults to the full stationed fleet; entering fewer units splits the fleet, leaving the remainder stationed | The MapView quantity input defaults to max; shows "splits fleet" label and remaining-behind count when the user reduces it. Arriving fleets auto-merge into any existing stationed fleet at the destination. |

---

## Expert Review Notes

*Added 2026-05-29. Findings are grounded in code review of `backend/app/tasks/tick.py`, `backend/app/routers/military.py`, `backend/app/routers/diplomacy.py`, and `backend/app/constants.py` alongside the spec.*

---

### Best Practice Violations



---

### Missing Features

**No new player starting tutorial or guided first actions.** Veteran players testing a closed beta will orient themselves, but the starting state (100 minerals, 100 fuel, 2000¤, 100 pop, one territory) gives no in-game signal about what to build first. OGame and Ikariam both have guided first-action queues. Without this, early beta feedback will include confusion about the correct opening sequence (mine → shipyard → fighters vs. mine → probe factory → exploration), which is actually a meaningful strategic choice the game should surface, not obscure.

**No way to split or merge stationed fleets.** A player with a stationed fleet of 200 fighters at one territory cannot split 50 to send somewhere while leaving 150. The `send_fleet` endpoint takes a `quantity` from the stationed fleet and creates a new in-transit fleet, which handles the split case. However, there is no endpoint to merge two stationed fleets at the same territory into one. If a player sends fighters to a territory in multiple waves, they accumulate as one stationed fleet (the arrival logic merges them), but this is not visible to the player as intentional behavior. CyberNations and P&W both have explicit fleet management UIs. Confirm whether the merge-on-arrival behavior is surfaced in the UI.

**No territory-level resource production breakdown.** The event log shows nation-level resource deltas per tick, but there is no endpoint that shows per-territory or per-facility production. Players cannot audit which territories are contributing what. CyberNations had a detailed income calculator; P&W shows per-city breakdowns. Without this, players cannot make informed decisions about where to build facilities or which territories to prioritize.

**No combat log accessible to third parties.** The events table records `combat_round` events, but the current `GET /log` view shows only events for the authenticated nation. In CyberNations and P&W, war histories are publicly visible — this is a social and diplomatic mechanic, not just a transparency feature. Veteran players will expect to be able to view another nation's recent combat history to assess their military activity.

---

### Balance Issues

**Probe cost is prohibitive at game start and the bootstrap problem is real.** A probe costs 10,000¤. Starting currency is 2,000¤. Territory income is 500¤/tick with at least one active facility. A new player needs 20 ticks (40 hours) of income to afford a single probe — and that assumes they spend nothing on facilities or fighters during that time. The probe factory itself costs 30 min + 15 fuel (cheap) but requires 20 assigned population, and the probe costs an additional 1,000 minerals and 500 fuel on top. The exploration archetype described as a legitimate path is mechanically inaccessible for roughly 2–3 real days after game start. Consider a starter probe allocation (1 probe in reserve at nation creation) or reducing the currency component for the first probe only.

**Currency income is linear with territory count but fighter upkeep is linear with fighter count, creating a perverse incentive.** 500¤/tick per active territory, 2¤/tick per fighter. A 5-territory nation earns 2,500¤/tick and can sustain 1,250 fighters on currency alone before considering other costs. There is no scaling cost for holding many territories (facility caps are a known missing feature). This means the dominant strategy is: colonize as many territories as possible as fast as possible to maximize currency income, then use that income to sustain a massive fighter force. The design intent (rim is viable, don't monopolize the core) is undercut by income that scales faster than any meaningful constraint. Infrastructure maintenance costs are post-beta — but without them, large empires accumulate currency faster than small ones with no counterbalancing pressure.

**Combat loss formula produces near-symmetrical attrition, making offensive war too costly.** With ATK 2 and HP 5, both attacker and defender lose `round(opponent_count × 0.4)` per tick. Equal-sized forces annihilate each other in about 2.5 ticks. An attacker who travels several ticks to reach an enemy territory then fights to mutual destruction gains nothing — the territory is conquered with a badly depleted force that then faces holding attrition. In CyberNations, the attacker/defender ratio was ~3:1 to overcome defenses (ground attack vs. defending soldiers). P&W builds in a resistance system where the defender does not lose forces until resistance reaches zero. The current symmetric formula means conquest is only viable with overwhelming numerical superiority, which requires large currency/fuel investment to manufacture. Consider giving the defender a meaningful advantage (e.g., defenders fight at 1.5× effectiveness when stationed on their own territory) or differentiate the DEF stat before the dissent system goes on top of an already attacker-unfavorable combat model.

**Holding fleet attrition applies even when a fleet is deliberately holding near friendly space.** The `holding` status applies both to fleets that expired their confirmation window at an enemy territory AND to any fleet that transitions from `pending_confirmation` on expiry with `standing_order = "hold"`. This means a player who intentionally sets standing order to "hold" (the default) to keep their fleet at an enemy border loses 1%/tick automatically. The attrition mechanic is correct for occupation/loitering scenarios but punishes players who use `hold` as a staging posture. The spec says the default standing order is `hold` — this means a player who forgets to set `recall` will silently watch their fleet erode at 1%/tick with no visible warning until the event log is checked. Consider a separate `staging` status or only applying attrition to fleets holding on enemy-owned territory.

**Resource drain targets nation stockpile, not territory.** The soft damage model drains 5% of the defender's total national mineral and fuel reserves per tick, regardless of how many territories are occupied or how large the nation is. A 10-territory nation with 50,000 minerals loses 2,500/tick from one occupied territory; a 1-territory nation with 500 minerals loses 25/tick. The drain is proportional to wealth, which means large nations are disproportionately affected per occupied territory. More importantly, the drain does not scale with the size of the attacking fleet — one fighter in occupation drains the same 5% as 500 fighters. This is not a soft damage model; it is a full-empire economic attack from a single unit. A more coherent implementation would drain a fixed amount per tick based on attacker fleet size or territory richness, rather than a percentage of total national wealth.

**Demolish refund is 25% of mineral/fuel cost but does not refund currency.** The `DEMOLISH_REFUND_FRACTION` applies to minerals and fuel only. A shipyard costs 2,000¤ to build and returns 0¤ on demolition. For facilities with significant currency costs (mine: 500¤, shipyard: 2,000¤), the player permanently loses all currency investment on demolition. In Ikariam and OGame, demolition returns a meaningful fraction of all resources. The current implementation will cause players to avoid demolition entirely (a strategic rigidity that worsens the facility-stacking problem already flagged in Known Open Issues) and creates a negative experience when players need to reorganize their infrastructure.

---

> **WARNING — change these before exposing the server to the internet.**
> This file is tracked by git. Remove this section or rotate these values before pushing to a public repo or opening a port to the outside world.

| Variable | Value |
|---|---|
| `DB_PASSWORD` | `SpationDev2026` |
| `SECRET_KEY` | `CaoTU4MqP5BVyuXc6ktbjEL7dG1pZ9RDAgWfKIHln3mYsxeO` |

These are written to `.env` (git-ignored). To rotate: update `.env` and restart the stack. Rotating `SECRET_KEY` invalidates all existing sessions.

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