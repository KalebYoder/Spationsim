# Project Context for Claude Code

This is a space-based browser nation simulator currently in active development. Read this file fully before making any suggestions or writing any code. Many decisions here were made deliberately — do not suggest alternatives unless explicitly asked.

---

## Vocabulary

- **Node** / **Territory** — interchangeable; same thing. "Node" preferred in code, "territory" in UI/design writing.
- **Planet** — any node where mineral_richness > 0 or fuel_richness > 0. Can be colonized.
- **Void** — any node where both mineral_richness = 0 and fuel_richness = 0. Cannot be colonized or developed, but can be claimed (ownership without population). Intended use: trade route control and wartime blockades.

---

## What This Game Is

A persistent multiplayer browser game where players control space-based nations on a shared map. Players expand through exploration and colonization, compete for resources, and engage in diplomacy and combat. Inspired by CyberNations and Politics & War but differentiated by player-friendly timer mechanics and an exploration/information economy.

This is not a real-time game. Actions are asynchronous. Players queue actions and log out. The game should be engaging to think about between sessions.

---

## Non-Negotiable Design Principles

These are core to the game's identity. Do not suggest changes to these.

**Inaction must never produce maximum harm.** All timer-based events default to the safe outcome if the player is not present. A fleet that arrives and finds the player offline holds in a visible confirmation window — it does not immediately attack.

**The confirmation window is 2 ticks (4 hours).** During this window the fleet is visible to the defender. Combat only triggers when the attacker confirms or the window expires. On expiry, the default standing order executes (hold or recall — never auto-attack).

**Vacation mode is frictionless to enter.** No cooldown, no minimum duration. Player becomes untargetable but cannot act or collect resources. Exit cooldown mechanics are TBD pending veteran player input — do not implement an exit cooldown without explicit instruction.

**Soft damage model for combat.** Undefended resources drain gradually over time, not all-or-nothing in a single strike.

**The rim is a viable permanent playstyle.** Rim territory has lower resources but lower conflict. New players are not permanently disadvantaged. Do not implement mechanics that make rim territory irrelevant at game maturity.

---

## Tech Stack

Do not suggest alternatives to these without being asked.

| Component | Choice |
|---|---|
| Host OS | Ubuntu 25.04 (Plucky Puffin) |
| Container base images | `python:3.12-slim` (backend/worker), `node:22-alpine` (frontend) — official language images, not CentOS |
| Containerization | Docker Compose |
| Database | PostgreSQL |
| Backend | Python / FastAPI |
| Task queue | Celery + Redis |
| Frontend | React (with Vite) |
| Reverse proxy | Nginx |
| DNS / DDoS | Cloudflare free tier |

**React specifics:** Keep it lean. No Redux or heavy state management libraries unless explicitly requested. Built-in React state is sufficient until proven otherwise.

**Celery + Redis:** All timed game events go through Celery. Do not handle timers in application logic or with cron jobs.

---

## Database Schema

Current schema. Do not modify table structures without explicit instruction.

```sql
CREATE TABLE players (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(64) UNIQUE NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login      TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE,
    vacation_mode   BOOLEAN DEFAULT FALSE,
    vacation_since  TIMESTAMPTZ
);

CREATE TABLE nations (
    id              SERIAL PRIMARY KEY,
    player_id       INTEGER REFERENCES players(id) UNIQUE NOT NULL,
    name            VARCHAR(128) UNIQUE NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    minerals        NUMERIC(12,2) DEFAULT 0,
    fuel            NUMERIC(12,2) DEFAULT 0,
    currency        NUMERIC(12,2) DEFAULT 0,
    diplomatic_status_default VARCHAR(16) DEFAULT 'neutral'
);

CREATE TABLE territories (
    id              SERIAL PRIMARY KEY,
    node_key        VARCHAR(32) UNIQUE NOT NULL,
    nation_id       INTEGER REFERENCES nations(id),
    mineral_richness NUMERIC(4,2) NOT NULL,
    fuel_richness   NUMERIC(4,2) NOT NULL,
    distance_from_center INTEGER NOT NULL,
    is_colonized    BOOLEAN DEFAULT FALSE,
    colonized_at    TIMESTAMPTZ
);

CREATE TABLE infrastructure (
    id              SERIAL PRIMARY KEY,
    territory_id    INTEGER REFERENCES territories(id) NOT NULL,
    type            VARCHAR(64) NOT NULL,
    level           INTEGER DEFAULT 1,
    population_assigned INTEGER DEFAULT 0,
    built_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE territory_population (
    territory_id    INTEGER REFERENCES territories(id) PRIMARY KEY,
    current         INTEGER DEFAULT 0,
    growth_rate     NUMERIC(5,4) DEFAULT 0.01,
    last_updated    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE probe_data (
    id              SERIAL PRIMARY KEY,
    territory_id    INTEGER REFERENCES territories(id) NOT NULL,
    discovered_by   INTEGER REFERENCES nations(id) NOT NULL,
    discovered_at   TIMESTAMPTZ DEFAULT NOW(),
    mineral_richness NUMERIC(4,2) NOT NULL,
    fuel_richness   NUMERIC(4,2) NOT NULL
);

CREATE TABLE probe_data_access (
    id              SERIAL PRIMARY KEY,
    probe_data_id   INTEGER REFERENCES probe_data(id) NOT NULL,
    granted_to      INTEGER REFERENCES nations(id) NOT NULL,
    granted_at      TIMESTAMPTZ DEFAULT NOW(),
    price_paid      NUMERIC(12,2),
    UNIQUE(probe_data_id, granted_to)
);

CREATE TABLE diplomacy (
    id              SERIAL PRIMARY KEY,
    nation_a        INTEGER REFERENCES nations(id) NOT NULL,
    nation_b        INTEGER REFERENCES nations(id) NOT NULL,
    status          VARCHAR(16) DEFAULT 'neutral',
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(nation_a, nation_b),
    CHECK(nation_a < nation_b)
);

CREATE TABLE fleets (
    id              SERIAL PRIMARY KEY,
    nation_id       INTEGER REFERENCES nations(id) NOT NULL,
    name            VARCHAR(128),
    origin_territory INTEGER REFERENCES territories(id),
    destination_territory INTEGER REFERENCES territories(id),
    unit_count      INTEGER DEFAULT 0,
    status          VARCHAR(32) DEFAULT 'stationed',
    departs_at      TIMESTAMPTZ,
    arrives_at      TIMESTAMPTZ,
    confirmation_expires_at TIMESTAMPTZ,
    standing_order  VARCHAR(32) DEFAULT 'hold',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE probes (
    id              SERIAL PRIMARY KEY,
    nation_id       INTEGER REFERENCES nations(id) NOT NULL,
    origin_territory INTEGER REFERENCES territories(id),
    destination_territory INTEGER REFERENCES territories(id),
    status          VARCHAR(32) DEFAULT 'in_transit',
    departs_at      TIMESTAMPTZ,
    arrives_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE events (
    id              SERIAL PRIMARY KEY,
    type            VARCHAR(64) NOT NULL,
    payload         JSONB,
    scheduled_for   TIMESTAMPTZ NOT NULL,
    processed_at    TIMESTAMPTZ,
    status          VARCHAR(16) DEFAULT 'pending'
);

CREATE TABLE resource_log (
    id              SERIAL PRIMARY KEY,
    nation_id       INTEGER REFERENCES nations(id) NOT NULL,
    tick_at         TIMESTAMPTZ NOT NULL,
    minerals_delta  NUMERIC(12,2),
    fuel_delta      NUMERIC(12,2),
    population_delta INTEGER,
    currency_delta  NUMERIC(12,2)
);
```

**Key schema decisions — do not reverse these:**
- Resources (minerals, fuel) stored at nation level as a pool; production happens at territory level and flows up each tick
- Population lives at territory level; nation total is derived by summing territories
- Diplomacy table enforces `nation_a < nation_b` so there is exactly one row per nation pair
- Events table exists alongside Celery to provide a persistent audit trail queryable without hitting Redis
- Alliance, trade route, and combat log tables are intentionally deferred to post-beta

---

## Resources

Three resource types for beta:

**Minerals** — basic construction resource, used for everything  
**Fuel** — used for ships, probes, and fleet movement  
**Population** — staffs mines and refineries; required to build colony ships and combat units; grows organically per tick based on infrastructure; lives at territory level

Population is a constraint resource, not a stockpile. You assign population to infrastructure. You cannot build or launch things without sufficient unassigned population.

---

## Game Systems Summary

**Tick system:** Every 2 hours. Handles resource generation, construction completion, probe movement, fleet movement, combat resolution. All via Celery.

**Probes:** Limited range (distance from nearest owned colony). Can be detected and destroyed passing through hostile territory — detection gives the owner an early warning notification, not just a silent block. Probe data is non-exclusive — seller retains it after sale. UI must show data age and whether coordinates are already colonized at time of purchase.

**Colonization:** Requires a colony ship. Ships travel through space — no leapfrogging through unclaimed space beyond probe range. Flanking via gradual leapfrog colonization is intentional and acceptable.

**Combat (beta):** Single unit type only. War declaration required before combat. Confirmation window on fleet arrival (2 ticks / 4 hours). Fleet is visible to defender during window. Standing orders: hold or recall (never auto-attack as default). Soft damage model — gradual resource drain, not all-or-nothing.

**Map:** 500–800 territory nodes for closed beta. Resource richness increases toward center. Distance from center stored on territory record.

**Alliances:** Not implemented in beta. Players organize via Discord.

---

## Current Development Phase

**Phase 1 — Foundation**
- [ ] Auth system (registration, login, sessions, security)
- [ ] Nation creation flow
- [ ] Rough draft UI skeleton
- [ ] Basic map representation (placeholder hex grid or node graph)

Do not build ahead of the current phase without instruction. Complete and test each phase before moving to the next.

---

## Development Order (Full)

1. Foundation (auth, nation creation, UI skeleton, map placeholder)
2. Economy (resources, tick system, construction)
3. Exploration (probes, colonization, information selling)
4. Combat (single unit type, war declaration, fleet movement, confirmation window)
5. Player interaction (trading, probe marketplace, diplomacy flags, messaging)
6. Closed alpha test

**Post-beta additions (do not implement yet):**
- Infrastructure maintenance costs
- Resource transport / trade routes
- More unit types and combat depth
- Alliance mechanics
- Espionage
- Map expansion
- Territory reversion / anti-squatting mechanics

---

## Open Questions (Do Not Implement Until Resolved)

- Does population die permanently in combat or reduce and recover?
- Vacation mode exit cooldown mechanics
- Population growth rate formula and what infrastructure types affect it
- Whether the new colony vulnerability window needs explicit mechanics

---

## Development Workflow

**Test-driven development is required for all new backend logic.**

For every new backend feature or service function:
1. Spawn the `qa-analyst` agent first to write the test suite before any implementation exists.
2. Implement against those tests.
3. Run the test file with `docker compose exec backend pytest tests/<test_file>.py -v` and confirm all pass before marking the task done.
4. After a feature is complete, run only its own test file — not the full suite. Full suite runs are periodic debug passes only.

Extract testable logic into pure service functions (in `backend/app/services/`) so the qa-analyst can test them without a running database. Follow the existing pattern: `pathfinding.py`, `combat.py`, `territory_yield.py`.

**Specialist agents to use proactively:**
- `qa-analyst` — write test suites before implementation (TDD first step)
- `game-expert` — design decisions, balance questions, genre research
- `dba` — any schema change, new index, or complex query
- `developer` — large multi-file feature implementation
- `Explore` — codebase search spanning more than 3 files

---

## Project Constraints

- Solo developer (infrastructure engineer background, not software product experience)
- Agentic AI-assisted development
- Closed beta with 20–50 veteran nation sim players
- Running on bare metal home server during beta (Xeon E3-1200, 16GB RAM)
- Minimize complexity — prefer simple and working over clever and fragile
- No budget for paid services during beta; free tiers only where external services are needed
