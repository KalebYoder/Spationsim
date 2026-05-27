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
- Event log page at `/log`: resource deltas, population changes, fleet events, combat, construction

### Exploration
- Probes: manufactured at probe factory (1000 min + 500 fuel + 10000¤ each), held in reserve, dispatched to destinations
- Probe range limited by distance from nearest owned colony
- Probe detection: territory owner notified on transit; probe destroyed if nations are at war
- Probe data: stored privately per nation, displayed in "Your Intelligence" table (coordinates, richness, time since discovery)
- Colony ships: built at shipyard (500 min + 1000 fuel each), hold up to 100 population, travel at 1 node/tick
- Colony ship load/unload at any owned colonized normal territory
- Territory claiming: a stationed fleet on an unclaimed normal territory claims it instantly; starts with zero population until a colony ship unloads
- Dynamic map generation: probes generate territory rows for uncharted hexes they scan; integer richness 1–5 weighted by distance from cluster center; void-zone anomalies at 1/1000 rate

### Combat & Military
- Single unit type: starfighter (ATK 2, DEF 1, HP 5, 2 nodes/tick; costs 15 min + 30 fuel + 1000¤ each)
- Fleet movement: dispatch, in-transit travel, arrival landing with merge into stationed fleet
- Vacation mode: instant entry, 48h minimum stay, 48h aggression lockout on exit, untargetable while active
- War declaration: 2-tick (4h) grace period before hostilities; blocked against vacation-mode targets; 24h minimum war duration
- Confirmation window: fleet entering enemy territory enters `pending_confirmation` for 2 ticks (4h); visible to both sides; attacker can confirm or recall; expiry executes standing order
- Standing orders: hold (default) or recall — applied on confirmation window expiry
- Basic combat resolution: engaged fleets fight stationed defenders each tick (`max(1, round(count × attack/hp))` losses each side); resource drain 5%/tick minerals + fuel when territory is undefended
- Holding fleet attrition: `max(1, round(unit_count × 0.01))` losses per tick; fleet deleted at zero with event logged

### Player Interaction
- Chat: public channels and direct messages with auto-tab on incoming DM
- Mail: inbox, outbox, delete
- Friends system: send/accept/refuse/cancel/remove requests; sidebar badge for incoming requests; friend_pending blocks fleet dispatch to that nation's planets
- Diplomacy statuses: neutral, war, war_pending, friendly, friend_pending
- Diplomatic name coloring: green (friendly/friend_pending), beige (neutral), red (war/war_pending) across map, probes, diplomacy, and friends pages
- Power metrics: military strength (1 per fighter, all statuses) and industrial strength (mine=1, refinery=1, shipyard=2, active only) — visible to all on nation profiles; visible to self on home page
- Territory rename cooldown: 24h (12 ticks); returns exact time remaining on 409

### Notifications & Events
- `territory_claimed` event includes `former_nation_id` in payload
- `territory_lost` event fires for the former owner when a territory changes hands

---

## What's Still To Do

### Remaining Feature Work

**Exploration (Phase 3)**
- [ ] Information selling — probe data marketplace; players list and purchase others' probe data; seller retains data; UI shows data age and whether the target is already colonized at time of purchase

**Combat (Phase 4)**
- [ ] Territory conquest — territory actually changing hands when an attacker wins; currently only resource drain occurs on undefended territory
- [ ] Pre-engagement skirmishing during `pending_confirmation` — small attrition losses each tick while fleet waits in the confirmation window (separate from holding fleet attrition, which is already implemented)

**Player Interaction (Phase 5)**
- [ ] Direct resource trading between players
- [ ] Probe data marketplace (frontend + transaction endpoints)

**Alpha Test (Phase 6)**
- [ ] Invite veteran player testers (closed beta)
- [ ] Publish public roadmap
- [ ] Establish feedback collection process

### Known Open Issues

**Balance**
- **Population growth rate** — currently 1%/tick. Territories fill to their richness-based cap quickly at low populations. Monitor during beta; may need to reduce to 0.1–0.5% if population becomes a non-constraint too quickly.
- **Holding fleet attrition rate** — currently `max(1, round(unit_count × 0.01))` (1%/tick, min 1). A 100-unit fleet lasts ~100 ticks (~200 hours). Monitor during beta; reduce to 0.5% if fleets disappear before players can act, increase to 2% if lurking remains a problem.

**Missing Standard Features**
- **No facility limits per territory** — players can stack unlimited facilities on a single tile. A population-capped center territory could staff 50 mines and generate 500 minerals/tick from one node, far exceeding any design intent. Needs a per-territory slot cap.

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

- Does population die permanently in combat, or does it reduce and recover? (Significant design weight — bring to veteran players)
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

---

## Dev Environment Credentials

> **WARNING — change these before exposing the server to the internet.**
> This file is tracked by git. Remove this section or rotate these values before pushing to a public repo or opening a port to the outside world.

| Variable | Value |
|---|---|
| `DB_PASSWORD` | `SpationDev2026` |
| `SECRET_KEY` | `CaoTU4MqP5BVyuXc6ktbjEL7dG1pZ9RDAgWfKIHln3mYsxeO` |

These are written to `.env` (git-ignored). To rotate: update `.env` and restart the stack. Rotating `SECRET_KEY` invalidates all existing sessions.
