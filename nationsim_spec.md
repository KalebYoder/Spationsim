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
- Requires a colony ship dispatched from existing territory
- Colony ships cannot leapfrog — must travel through or around existing space
- Flanking via slow leapfrog colonization is intentional and acceptable; it costs resources and is visible

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
| Fleet arrives and combat triggers while offline | Confirmation window (30–60 min); combat only triggers on confirm or window expiry |
| Can't step away during time-sensitive event | Vacation/pause mode — instant, no cooldown, no minimum duration; makes you untargetable but also unable to act or collect |
| Missed timer = total loss | Soft damage model — gradual resource drain rather than single catastrophic strike |
| No control over offline fleet behavior | Standing orders — pre-set contingency actions (hold, recall, etc.) |

---

## Tech Stack

| Component | Choice | Status | Notes |
|---|---|---|---|
| Server | Bare metal home server (Xeon E3-1200, 16GB RAM, ~20TB free) | N/A (deployment) | Sufficient for closed beta |
| OS | CentOS Linux | N/A (deployment) | Familiar to developer |
| Containerization | Docker Compose | **Done** | All services defined with health checks |
| Database | PostgreSQL | **Done** | Service configured; full SQLAlchemy model layer with DBA-reviewed indexes |
| Backend | Python / FastAPI | **Done** | App skeleton, auth router, all ORM models |
| Task Queue | Celery + Redis | **Partial** | Redis service running; `celery` in requirements.txt — no worker service, no app instance, no tasks defined yet |
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

## Development Order

### Phase 1 — Foundation
- [x] Auth system (registration, login, sessions, security)
- [ ] Nation creation flow
- [ ] Rough draft UI skeleton
- [ ] Basic map representation (placeholder — hex grid or node graph)

### Phase 2 — Economy
- [ ] Resource types defined
- [ ] Territory resource values assigned
- [ ] Tick system (Celery + Redis)
- [ ] Resource generation per territory per tick
- [ ] Construction system (basic improvements)

### Phase 3 — Exploration
- [ ] Probe mechanic (dispatch, travel, arrival)
- [ ] Probe range limits (distance from nearest colony)
- [ ] Probe detection by territory owners
- [ ] Probe data storage (private to player)
- [ ] Colonization mechanic (colony ship dispatch + arrival)
- [ ] Information selling between players

### Phase 4 — Combat
- [ ] Single unit type
- [ ] War declaration system
- [ ] Fleet movement
- [ ] Confirmation window on fleet arrival
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
| Vacation mode exit cooldown | Defer to veteran player input | Known abuse vector in other games; needs input from experienced players before deciding |

## Open Questions

- Does population die permanently in combat, or does it reduce and recover? (Significant design weight — bring to veteran players)
- Vacation mode exit cooldown mechanics (bring to veteran players)
- Population growth rate and what infrastructure affects it
- Whether colony vulnerability window (low population, low development) creates enough natural strategic depth or needs explicit mechanics

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

*Last updated: auth system complete, Celery worker still needed, Phase 1 in progress*
