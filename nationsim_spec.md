# Nation Sim — Project Specification
*Working document. Update as decisions are made.*

---

## Concept Summary

A space-based browser nation simulator in the vein of CyberNations and Politics & War, differentiated by:
- A shared persistent world map with finite but expandable territory
- Player-driven exploration and colonization mechanics
- An information economy around probe/scout data
- Timer mechanics designed to not punish players for having a life

Players control space-based nations. Territory exists on a shared map. Conflict arises naturally from resource scarcity and territorial ambition rather than being purely consensual.

---

## Core Design Principles

**Inaction should never produce maximum harm.**
All timer-based events should default to the safe outcome if the player is not present. Players can set contingency orders (e.g. "recall fleet if I don't confirm within X hours").

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

## Core Systems

### Resource System
- 2–3 resource types for beta (expand later)
- Resources generated on a tick system (frequency TBD, likely every 2 hours)
- Resource density tied to territory location (center vs rim)
- Players collect resources automatically — no manual collection required

### Exploration & Probes
- Players send probes to scout unclaimed territory
- Probe range limited by distance from nearest owned colony
- Probes can be detected and destroyed when passing through hostile territory
  - Detection gives the territory owner an early warning, not just a block
- Probe data (coordinates + resource/terrain info) is private to the discovering player
- Data can be sold or traded to other players
- Colonized territory is immediately visible to all players on the map (stale data problem self-solves)
- Scouting costs resources; colonization costs significantly more

### Colonization
- Two-step process: claim first, then populate
- **Claiming unclaimed territory**: a stationed fleet (starfighters) on an unclaimed normal territory can claim it immediately via a player action. The territory becomes owned but starts with zero population — no resource extraction or facility construction is possible until population is transferred.
- **Populating claimed territory**: colony ships transport population from an existing territory to a newly claimed one. A colony ship holds up to 100 population, travels at 1 node/tick, and can load/unload at any colonized normal territory owned by the player. Colony ships are built at shipyards (500 minerals, 1000 fuel each).
- Probes cannot claim territory.
- Colony ships cannot leapfrog — must travel through owned or at least reachable space (distance-based, no path-tracing in beta).
- Flanking via slow leapfrog colonization is intentional and acceptable; it costs resources and is visible.

### Information Economy
- Probe data is a tradeable commodity
- Timestamps on data so buyers know how old it is
- Espionage mechanic to steal probe data (post-beta)
- Explorer archetype: specialize in scouting and selling information rather than military expansion

### Tick System
- Heartbeat of the game
- Handles: resource generation, construction completion, probe movement, combat resolution
- Implemented via Celery + Redis
- All timed events default to safe outcome on expiration if player has not confirmed

### Construction & Infrastructure
- Players build improvements on colonized territory
- **Facility types (beta):** Mine (minerals), Refinery (fuel), Shipyard (starfighters + colony ships), Probe Factory (probes)
- Shipyard replaces the earlier "fighter factory" concept — it builds both combat units and colony ships from a single facility
- Production formula: `round(2 × territory_richness)` per facility per tick
- Each facility type has a population assignment cost (Mine: 10, Refinery: 10, Probe Factory: 20, Shipyard: 40)
- Infrastructure has maintenance costs (post-beta: costs scale over time to cap maximum nation size)
- Military units require infrastructure support on player territory (supply chain — post-beta)

### Combat (Beta: Rudimentary)
- Single unit type for initial beta
- Basic attack/defend resolution
- War declaration required before combat (no surprise attacks)
- Confirmation window on fleet arrival — combat does not trigger immediately
- Players can set standing orders for fleet behavior when offline
- Soft damage model: undefended resources drain gradually rather than all-or-nothing on single strike

### Player Interaction
- Direct resource trade between players
- Probe data buying/selling
- War declaration
- Basic diplomatic status: allied / neutral / hostile
- Alliance mechanics deferred to post-beta; players use Discord to organize during alpha

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

### Future Hosting Path
1. Home server (beta)
2. Hetzner dedicated server (~€40–60/month) if traction develops
3. Revisit AWS/Azure only if scaling exceeds what Hetzner can handle (unlikely for this game type)

---

## Known Issues / To-Fix List

*Identified by game design review against genre best practices. Ordered by priority.*

### Best Practice Violations

1. **Resource richness ignored in production** — *(Fixed)* Production is now `round(2 × richness)` per facility per tick.

2. **Starfighters stored as a nation-level count, not positioned fleets** — *(Fixed)* Fleets are rows in the `fleets` table with `origin_territory` tracking location; in-transit fleets have `destination_territory` and `arrives_at`; the tick lands them each cycle.

3. **Population growth uncapped and independent of player action** — *(Fixed)* Growth is 5% per tick, capped at `50 × (mineral_richness + fuel_richness)` per territory.

4. **No persistent map page** — *(Fixed)* MapView page exists with hex grid, fleet deployment workflow, and territory ownership display.

5. **No colonization mechanic with no territory limit** — *(Fixed)* Two-step colonization: fleets claim unclaimed territory, colony ships transport population. Newly claimed territory has zero population until a colony ship unloads there.

6. **Vacation mode has no exit cooldown** — *(Fixed)* 48-hour minimum stay enforced on entry; 48-hour aggression lockout applied on exit (blocks fleet dispatch and vacation re-entry). See Decisions Log.

### Missing Standard Features

1. **No player-to-player interaction** — No trade, messaging, or war declaration. Need at least one social mechanism for beta; even resource gifting suffices.

2. **No tick event log** — Players have a countdown but no record of what changed last tick. Standard: event log or last-tick summary showing production, population delta, probe arrivals.

3. **No facility limits per territory** — No reason to hold more than one territory if facilities can stack infinitely at home. Needs a per-territory slot cap.

4. **No military upkeep** — Units cost population to build but have zero ongoing cost. Players stockpile indefinitely with no decay loop. Fuel upkeep is the standard mechanism.

5. **No score or power metric** — No competitive reference frame for beta players; no matchmaking signal for combat. Even a simple composite stat on a leaderboard suffices.

6. **Probe reward loop closed** — Probes are manufactured and moved but results can't be viewed in the UI and can't be shared. Need a probe report view.

7. **No per-territory base income** — Only income is mines and refineries; strategic question reduces to "how many facilities do I build." Small per-territory flat income would give rim territories value.

8. **Territory renaming has no cooldown** — Can be used to confuse map intel mid-war. One-tick cooldown sufficient.

---

## Development Order

### Phase 1 — Foundation
- [x] Auth system (registration, login, sessions, security)
- [x] Nation creation flow
- [x] Rough draft UI skeleton
- [x] Basic map representation (hex grid MapView with fleet deployment)

### Phase 2 — Economy
- [x] Resource types defined (minerals, fuel, population)
- [x] Territory resource values assigned (richness on map generation)
- [x] Tick system (Celery + Redis, 2-hour interval)
- [x] Resource generation per territory per tick (`round(2 × richness)` per facility)
- [x] Construction system (mine, refinery, shipyard, probe factory)
- [x] Population system (5% growth per tick, richness-based cap, assignment to facilities)
- [x] Fleet arrival processing in tick

### Phase 3 — Exploration
- [x] Probe mechanic (manufacture at probe factory, reserve system)
- [x] Colony ship mechanic (build at shipyard, population transport, load/unload)
- [x] Territory claiming (stationed fleet claims unclaimed territory; no population until colony ship unloads)
- [ ] Probe dispatch and travel
- [ ] Probe range limits (distance from nearest colony)
- [ ] Probe detection by territory owners
- [ ] Probe data storage (private to player) and UI report view
- [ ] Information selling between players

### Phase 4 — Combat
- [x] Single unit type (starfighter: ATK 2, DEF 1, HP 5, 2 nodes/tick)
- [x] Fleet movement (send, in-transit, arrival processing)
- [x] Vacation mode (48h min stay, 48h aggression lockout on exit)
- [ ] War declaration system
- [ ] Confirmation window on fleet arrival (backend logic — UI placeholder exists)
- [ ] Basic combat resolution
- [ ] Standing orders (hold/recall defaults)

### Phase 5 — Player Interaction
- [ ] Direct resource trading
- [ ] Probe data marketplace
- [ ] Diplomatic status flags
- [ ] Basic player messaging

### Phase 6 — Alpha Test
- [ ] Invite veteran player testers (closed)
- [ ] Public roadmap published
- [ ] Feedback collection process established

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

## Decisions Log

| Question | Decision | Notes |
|---|---|---|
| Tick frequency | 2 hours | Standard for genre; revisit after beta feedback |
| Resources for beta | Minerals, Fuel, Population | Population staffs mines/refineries and is required for colony ships and combat units; grows organically over time, affected by infrastructure |
| Map size | 500–800 territory nodes | Supports 20–50 testers with room to expand before natural collision; revisit based on observed expansion rates |
| Probe data transfer | Non-exclusive | Seller retains data; UI shows data age and colonization status at time of purchase to mitigate scam potential |
| Confirmation window | 2 ticks (4 hours) | Consistent with game's internal logic; fleet holds visibly during window so defender can see it, call for help, and diplomacy can occur |
| Vacation mode mechanics | Option 3: aggression lockout on exit | 48-hour minimum stay enforced; 48-hour post-exit lockout blocks fleet dispatch, colony ship dispatch, and vacation re-entry. Surveyed CyberNations, P&W, OGame, Ikariam — chosen approach maps cleanly onto single-unit-type beta. Vacation entry history is also public on player profile (transparency without additional restriction). |
| Colonization method | Two-step: fleet claims, colony ship populates | Fleets (starfighters) claim unclaimed territory on arrival; territory starts with zero population. Colony ships (500 minerals, 1000 fuel, 1 node/tick, 100 pop capacity) transfer population to enable facility construction and resource extraction. Probes cannot claim. |
| Shipyard replaces fighter factory | Yes | Single facility builds both starfighters and colony ships. Costs 50 minerals, 20 fuel to build; requires 40 assigned population to operate. |
| Colony ship build cost | 500 minerals, 1000 fuel | No population cost at build time — colony ships are vessels, not population units. Population consumed only via the load action. |

## Open Questions

- Does population die permanently in combat, or does it reduce and recover? (Significant design weight — bring to veteran players)
- Population growth rate tuning and whether specific infrastructure types (beyond mines/refineries) should influence it.
- Whether colony vulnerability window (low population, low development) creates enough natural strategic depth or needs explicit mechanics.
- **Vacation mode as a territory blocker**: a player in vacation mode indefinitely still denies staging ground during alliance wars. The 48h lockout solves rapid in/out exploitation but not a committed long-term blocker. Possible solutions (not yet designed): war-declaration entry block; minimum fleet-presence requirement to invoke vacation; admin enforcement. Defer until beta feedback confirms whether this is a real problem in practice.

---

---

## Dev Environment Credentials

> **WARNING — change these before exposing the server to the internet.**
> This file is tracked by git. Remove this section or rotate these values before pushing to a public repo or opening a port to the outside world.

| Variable | Value |
|---|---|
| `DB_PASSWORD` | `SpationDev2026` |
| `SECRET_KEY` | `CaoTU4MqP5BVyuXc6ktbjEL7dG1pZ9RDAgWfKIHln3mYsxeO` |

These are written to `.env` (git-ignored). To rotate: update `.env` and restart the stack. Rotating `SECRET_KEY` invalidates all existing sessions.

---

*Last updated: Phases 1–2 complete, Phase 3 partial (colony ships + claiming done; probe dispatch/detection/data pending), Phase 4 partial (fleet movement + vacation mode done; war declaration + combat resolution pending)*
