# Codebase Map

Quick reference for finding where features are defined and implemented.

---

## Directory Layout

```
spationsim/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app, router registration
│   │   ├── constants.py          # All game tuning constants
│   │   ├── map_gen.py            # Map/territory generation
│   │   ├── seed.py               # Database seeding script
│   │   ├── celery_app.py         # Celery instance
│   │   ├── core/
│   │   │   ├── config.py         # Environment config (DB URL, secrets)
│   │   │   └── security.py       # Password hashing, JWT
│   │   ├── db/
│   │   │   └── database.py       # SQLAlchemy engine, SessionLocal, Base
│   │   ├── models/               # ORM table definitions
│   │   ├── routers/              # FastAPI route handlers (API endpoints)
│   │   ├── schemas/              # Pydantic request/response types
│   │   ├── services/             # Pure business logic functions (testable without DB)
│   │   └── tasks/
│   │       └── tick.py           # Celery tick task — the game loop
│   ├── migrations/               # SQL ALTER TABLE migration files
│   └── tests/                    # pytest test suite
├── frontend/
│   └── src/
│       ├── App.jsx               # Route definitions
│       ├── main.jsx              # React entry point
│       ├── components/           # Shared UI components
│       ├── context/              # React context providers
│       ├── hooks/                # Reusable data-fetching hooks
│       ├── pages/                # One file per page/route
│       └── styles/
│           └── theme.css         # CSS variables (colors, spacing)
├── nationsim_spec.md             # Game design spec and decisions log
├── CLAUDE.md                     # AI assistant instructions and project rules
└── docker-compose.yml            # Service definitions
```

---

## Backend Models (`backend/app/models/`)

Each file is one database table.

| File | Table | What it stores |
|---|---|---|
| `player.py` | `players` | Auth accounts — username, email, password hash, vacation mode |
| `nation.py` | `nations` | Nation record — resource pools (minerals, fuel, currency), owner player |
| `territory.py` | `territories` | Map nodes — richness, ownership, colonized state, distance from center |
| `territory_population.py` | `territory_population` | Per-territory current population count |
| `territory_dissent.py` | `territory_dissent` | Per-territory dissent value (0–100) |
| `infrastructure.py` | `infrastructure` | Facilities — type, status (active/under_construction/demolishing), territory |
| `fleet.py` | `fleets` | Fleets — status, unit count, origin/destination, timers including `occupation_expires_at` |
| `colony_ship.py` | `colony_ships` | Colony ships — separate from fleets, carry population cargo |
| `probe.py` | `probes` | Dispatched probes in transit |
| `probe_data.py` | `probe_data` | Scan results stored per territory per discovering nation |
| `probe_visibility.py` | `probe_visibility` | Which territories each nation can see on the map |
| `probe_market.py` | `probe_market` | Public marketplace listings for probe data |
| `diplomacy.py` | `diplomacy` | Nation-pair relations — status (neutral/friend/war/war_pending), `declared_by`, `is_lopsided` |
| `event.py` | `events` | Append-only audit log of all game events (JSONB payload) |
| `resource_log.py` | `resource_log` | Per-tick resource delta records for the event log UI |
| `mail_message.py` | `mail_messages` | Player-to-player messages |
| `chat_message.py` | `chat_messages` | Global and DM chat |
| `trade.py` | `trades` | Resource trade offers between nations |
| `tutorial.py` | `tutorial_state` | Per-nation tutorial progress tracking |

---

## Backend API Endpoints (`backend/app/routers/`)

### `/api/auth` — `auth.py`
| Method | Path | What it does |
|---|---|---|
| POST | `/register` | Create player account |
| POST | `/login` | Start session (sets cookie) |
| POST | `/logout` | End session |
| GET | `/me` | Current authenticated player |

### `/api/nations` — `nations.py`
| Method | Path | What it does |
|---|---|---|
| GET | `` | List all nations |
| POST | `` | Create nation (nation creation flow) |
| GET | `/mine` | Your own nation's full data |
| POST | `/me/vacation/enter` | Enter vacation mode |
| POST | `/me/vacation/exit` | Exit vacation mode |
| GET | `/mine/territories/yields` | Per-territory production breakdown |
| GET | `/mine/territories` | Your territories with population and dissent |
| GET | `/{id}/territories` | Another nation's visible territories |
| GET | `/list` | Nation list for search/autocomplete |
| GET | `/{id}` | Public nation profile |
| GET | `/{id}/wars` | War history for a nation |
| GET | `/{id}/wars/{opp}/log` | Combat event log for a specific war |
| GET | `/{id}/wars/{opp}/status` | Current war status summary |

### `/api/territories` — `territories.py`
| Method | Path | What it does |
|---|---|---|
| GET | `` | All visible territories (map data) |
| GET | `/map-fleets` | Fleet positions for map overlay |
| GET | `/available` | Territories with no owner (colonization candidates) |
| PATCH | `/{id}/name` | Rename a territory you own |

### `/api/facilities` — `facilities.py`
| Method | Path | What it does |
|---|---|---|
| GET | `` | All your facilities across all territories |
| POST | `` | Build a facility (mine/refinery/shipyard/propaganda_office) |
| POST | `/{id}/demolish` | Start demolishing a facility |

### `/api/military` — `military.py`
| Method | Path | What it does |
|---|---|---|
| GET | `/units` | Unit stats (starfighter constants) |
| GET | `/fleets` | Your fleets with status and location |
| GET | `/fleets/pending-at-mine` | Enemy fleets in pending_confirmation at your territories |
| POST | `/manufacture/starfighter` | Build fighters at a shipyard |
| POST | `/fleets/send` | Dispatch a fleet to a destination |
| POST | `/fleets/{id}/confirm-attack` | Confirm attack during 4-hour window |
| POST | `/fleets/{id}/recall` | Recall a fleet (pending_confirmation, holding, or occupying) |
| POST | `/fleets/{id}/occupy` | Formally claim territory during occupation window |
| POST | `/fleets/{id}/rout` | Post-battle: deal bonus damage to fleeing defenders |
| POST | `/fleets/{id}/raid` | Post-battle: steal resources from the territory |
| POST | `/fleets/{id}/raze` | Post-battle: destroy a facility |
| POST | `/fleets/{id}/claim` | Claim an unclaimed/neutral territory (no combat required) |
| GET | `/colony-ships/stats` | Colony ship manufacture costs |
| GET | `/colony-ships` | Your colony ships |
| POST | `/manufacture/colony-ship` | Build a colony ship |
| POST | `/colony-ships/{id}/send` | Dispatch a colony ship |
| POST | `/colony-ships/{id}/load` | Load population cargo onto a ship |
| POST | `/colony-ships/{id}/unload` | Unload population at destination |

### `/api/probes` — `probes.py`
| Method | Path | What it does |
|---|---|---|
| GET | `/stats` | Probe manufacture costs and range |
| POST | `/manufacture` | Build a probe |
| GET | `/active` | Probes currently in transit |
| POST | `/dispatch` | Dispatch a probe to a destination |
| POST | `/{id}/recall` | Recall a probe |
| GET | `/data` | Your probe scan results |

### `/api/diplomacy` — `diplomacy.py`
| Method | Path | What it does |
|---|---|---|
| GET | `/friends` | Your friends list |
| GET | `/relations` | All your diplomatic relations |
| GET | `/{id}` | Relation with a specific nation |
| POST | `/war` | Declare war (sets `is_lopsided` flag) |
| PUT | `/{id}` | Set relation (neutral/friend/war_pending/ceasefire) |
| POST | `/{id}/friend-request` | Send friend request |
| POST | `/{id}/accept-friend` | Accept a friend request |
| POST | `/{id}/refuse-friend` | Decline a friend request |
| POST | `/{id}/remove-friend` | Remove a friend |
| GET | `/wars` | All active wars |

### `/api/economy` — `economy.py`
| Method | Path | What it does |
|---|---|---|
| GET | `/last-tick` | Resources at the last tick |
| GET | `/population` | Nation population summary |
| GET | `/flow` | Per-tick resource income/cost breakdown |

### `/api/probe-market` — `probe_market.py`
| Method | Path | What it does |
|---|---|---|
| GET | `` | All marketplace listings |
| POST | `` | List probe data for sale |
| DELETE | `/{id}` | Remove your listing |
| POST | `/{id}/buy` | Purchase a probe data listing |

### `/api/trade` — `trade.py`
| Method | Path | What it does |
|---|---|---|
| GET | `` | Your trades (incoming and outgoing) |
| GET | `/route/{nation_id}` | Trade route info to a nation |
| POST | `` | Create a trade offer |
| PUT | `/{id}` | Edit a pending trade offer |
| POST | `/{id}/accept` | Accept an incoming trade |
| POST | `/{id}/reject` | Reject an incoming trade |
| POST | `/{id}/cancel` | Cancel your outgoing trade |

### Other routers
| Router | Prefix | What it covers |
|---|---|---|
| `mail.py` | `/api/mail` | Inbox, outbox, send, delete |
| `chat.py` | `/api/chat` | Global chat messages, DM channels |
| `events.py` | `/api/events` | `/log` — event log with resource deltas per tick |
| `notifications.py` | `/api/notifications` | Badge counts: mail, threats, trade, fleet pending action |
| `tutorial.py` | `/api/tutorial` | Tutorial state, step completion, dismiss |

---

## Backend Services (`backend/app/services/`)

Pure functions — no HTTP, no DB sessions in the function signature (except where noted). All tested independently.

| File | Function(s) | What it does |
|---|---|---|
| `combat.py` | `resolve_combat_tick(attacker, stats, defender, stats, multiplier)` | One tick of fleet vs fleet combat. Returns `(attacker_losses, defender_losses)`. Home-territory multiplier inflates defender effective count. |
| `dissent.py` | `compute_territory_dissent_delta(at_war, is_aggressor, fleet_status, has_po, ...)` | Net dissent change for one territory in one tick. Sums sources (war, enemy fleet) then subtracts decay (peace/war base + PO bonus). |
| `logistics.py` | `compute_logistics_fuel_cost(territory_count, k)` | Quadratic territory fuel upkeep: `k × N(N+1)/2`. |
| `pathfinding.py` | `compute_reachable_ids(territories, origin_key, max_distance)` | BFS over territory graph; returns set of reachable territory IDs within a distance limit. Used to validate fleet dispatch range. |
| `power.py` | `military_strength(db, nation_id)` | Total unit count across all stationed + in-transit fleets. Used for lopsided-war detection at war declaration. |
| `territory_yield.py` | `compute_territory_yield(territory, facilities, population, dissent)` | Per-territory per-tick mineral/fuel/currency production. Applies `dissent_production_modifier`. |
| `territory_yield.py` | `dissent_production_modifier(dissent)` | Production multiplier from dissent: 1.0 at 0, ~0.5 at 75, 0 at 100. Uses `DISSENT_CURVE_EXPONENT`. |
| `tutorial.py` | Various helpers | Step completion logic, reward lookup, action-to-step mapping. |

---

## The Tick (`backend/app/tasks/tick.py`)

The entire game loop runs in `run_tick()`, called by Celery every 2 hours. Sections in order:

1. **War pending promotion** — `war_pending` rows past their grace period become `war`
2. **In-transit fleet arrival** — fleets whose `arrives_at ≤ now` land and enter `pending_confirmation` or `holding`
3. **Pending confirmation expiry** — unconfirmed attacks execute standing order (hold or recall) after 4 hours
4. **Post-battle choice expiry** — expired `post_battle_choice` fleets return to `engaged`
5. **Engaged fleet combat** — per-tick combat resolution; defenders at 0 → attacker enters `occupying`
6. **Holding fleet attrition** — `HOLDING_ATTRITION_RATE` loss/tick, only when enemy stationed fleet shares the territory
7. **Occupation window processing** — check enemy return (→ `holding`) and expiry (→ auto-recall)
8. **Dissent update** — compute delta for every colonized territory; log threshold crossings
9. **Colony ship arrival** — landed ships enter `stationed`
10. **Resource generation** — `compute_territory_yield` per territory; pools written to `nations`
11. **Population growth** — `max(1, round(pop × POPULATION_GROWTH_RATE))` per territory, capped
12. **Currency and fuel upkeep** — fleet currency upkeep, fleet fuel upkeep (when not docked), logistics fuel upkeep
13. **Facility completion** — `under_construction` facilities whose `completes_at ≤ now` become `active`
14. **Demolish completion** — `demolishing` facilities removed; partial refund applied
15. **Resource log** — net deltas written to `resource_log` for the event log UI
16. **Probe movement** — probes advance one node per tick; detection checked on hostile territory
17. **Probe arrival** — arrived probes scan territory and write `probe_data`

---

## Game Constants (`backend/app/constants.py`)

All tuning knobs in one place. Key ones:

| Constant | Value | What it controls |
|---|---|---|
| `UNIT_STATS["starfighter"]` | FP 2, Shields 1, SI 5, 2 nodes/tick | Combat formula inputs and fleet speed |
| `HOLDING_ATTRITION_RATE` | 0.025 | 2.5%/tick attrition when contested |
| `HOME_TERRITORY_DEFENSE_MULTIPLIER` | 1.5 | Defender bonus on own colonized territory |
| `LOGISTICS_FUEL_K` | 1 | Quadratic territory fuel upkeep scaling |
| `TERRITORY_UPKEEP_K` | 10 | Quadratic territory currency upkeep scaling |
| `DISSENT_WAR_AGGRESSOR` | 3 | Dissent/tick on aggressor's territories during war |
| `DISSENT_WAR_DEFENDER` | 2 | Dissent/tick on defender's territories during war |
| `DISSENT_FLEET_HOLDING` | 6 | Dissent/tick for enemy holding fleet on territory |
| `DISSENT_FLEET_ENGAGED` | 10 | Dissent/tick for enemy engaged fleet on territory |
| `DISSENT_CONQUEST_RESET` | 60 | Instant dissent value set on formal occupation |
| `DISSENT_LOPSIDED_MULTIPLIER` | 1.5 | Multiplier on aggressor dissent for lopsided wars (>3:1 military ratio) |
| `DISSENT_OFFICE_BONUS_AGGRESSOR` | 1 | PO decay bonus cap while the nation is the declared aggressor |
| `DISSENT_CURVE_EXPONENT` | 1.71 | Shape of production penalty curve |
| `PROBE_RANGE` | 10 | Max probe dispatch distance from nearest owned colony |
| `FACILITY_POPULATION_COST` | mine 10, refinery 10, shipyard 40, PO 20 | Workers consumed per facility |
| `FACILITY_BUILD_TICKS` | mine/refinery 1, shipyard/PO 2 | Construction time |

---

## Database Migrations (`backend/migrations/`)

Applied manually with `psql -U spationsim spationsim -f <file>`. Numbered sequentially.

| File | What it adds |
|---|---|
| `001` | Rename fighter_factory → shipyard |
| `002` | Aggression lockout on vacation exit |
| `003` | Messaging (mail, chat) tables |
| `004` | `probe.current_territory` column |
| `005` | Facility construction (`status`, `completes_at`) |
| `006` | `war_pending` status + `war_starts_at` on diplomacy |
| `007` | Friend requests on diplomacy |
| `008` | Remove `growth_rate` from territory_population |
| `009` | Trades table |
| `010` | Trade confirmations |
| `011` | War eligibility columns (`last_war_ended_at`, `aggression_lockout_until`) |
| `012` | War duration and cooldown |
| `013` | Probe detection tracking |
| `014` | `is_lopsided` on diplomacy |
| `015` | `occupation_expires_at` on fleets |

---

## Frontend Pages (`frontend/src/pages/`)

| File | Route | What the player sees |
|---|---|---|
| `Login.jsx` | `/login` | Login form |
| `Register.jsx` | `/register` | Registration form |
| `NationCreate.jsx` | `/create-nation` | Nation creation (name, flag color) |
| `Home.jsx` | `/` | Nation overview: resources, population, recent events |
| `Economy.jsx` | `/economy` | Resource flow, upkeep breakdown, population table |
| `Facilities.jsx` | `/facilities` | Build/demolish facilities; construction queue |
| `Military.jsx` | `/military` | Manufacture fighters, dispatch fleets, active operations (all fleet statuses + actions) |
| `Probes.jsx` | `/probes` | Manufacture and dispatch probes, view scan results |
| `MapView.jsx` | `/map` | Hex grid map, territory ownership, fleet dispatch workflow |
| `Planets.jsx` | `/planets` | Your colonized territories with stats |
| `Diplomacy.jsx` | `/diplomacy` | War declarations, ceasefire, relation flags |
| `FriendsList.jsx` | `/friends` | Friend requests, friends list |
| `Trade.jsx` | `/trade` | Incoming/outgoing trade offers |
| `Mail.jsx` | `/mail` | Inbox/outbox, compose |
| `ProbeMarket.jsx` | `/market` | Browse and buy probe data listings |
| `EventLog.jsx` | `/log` | Per-tick resource deltas and game events |
| `CombatLog.jsx` | (linked from Military) | Combat round history for active wars |
| `NationProfile.jsx` | `/nations/:id` | Public view of another nation |

---

## Frontend Components (`frontend/src/components/`)

| File | What it does |
|---|---|
| `Layout.jsx` | Sidebar nav with badge counts; 45-second notification poll; browser Notification API (bell icon) |
| `ChatWindow.jsx` | Floating global/DM chat; polls every 4 seconds |
| `NationSearch.jsx` | Top-bar nation search input |
| `ProtectedRoute.jsx` | Redirects to `/login` if not authenticated |
| `TutorialPanel.jsx` | Sidebar tutorial step panel |
| `ui.jsx` | Shared primitives: `EmptyState`, `Spinner`, etc. |

## Frontend Context & Hooks

| File | What it provides |
|---|---|
| `context/AuthContext.jsx` | `useAuth()` — current player, login/logout, session state |
| `context/NationContext.jsx` | `useNation()` — current nation data, shared across pages |
| `hooks/useNation.js` | Thin wrapper that reads from NationContext |
| `hooks/useDiplomacy.js` | Fetches and caches diplomatic relations |
| `hooks/useTutorial.js` | Tutorial state, dismiss, step completion actions |

---

## Tests (`backend/tests/`)

| File | What it covers |
|---|---|
| `conftest.py` | `db_session`, `client`, player/nation fixture helpers |
| `test_combat.py` | `resolve_combat_tick` formula, home-territory multiplier |
| `test_dissent.py` | `compute_territory_dissent_delta` for all source/decay combinations |
| `test_dissent_lopsided.py` | Lopsided-war multiplier activation and PO aggressor cap |
| `test_home_territory_multiplier.py` | Defense multiplier in full tick combat |
| `test_occupation_window.py` | `occupying` status, expiry recall, enemy cancellation, `/occupy` endpoint |
| `test_holding_attrition.py` | Attrition only fires with enemy stationed fleet present |
| `test_confirmation_window.py` | Fleet pending_confirmation, standing orders, expiry |
| `test_war.py` | War declaration, grace period, ceasefire |
| `test_war_eligibility.py` | Cooldown and adjacency rules |
| `test_logistics.py` | `compute_logistics_fuel_cost` |
| `test_fleet_fuel_upkeep.py` | Fuel drain for non-docked fleets |
| `test_upkeep.py` | Territory currency upkeep (quadratic formula) |
| `test_territory_yield.py` | `compute_territory_yield`, dissent production modifier |
| `test_fleet_pathfinding.py` | `compute_reachable_ids`, probe range enforcement |
| `test_probe_intelligence.py` | Probe dispatch, scan, detection |
| `test_probe_map_expansion.py` | Probe visibility radius |
| `test_probe_pregenerates_before_movement.py` | Probe movement tick ordering |
| `test_power_metrics.py` | `military_strength` calculation |
| `test_currency.py` | Currency income and upkeep tick |
| `test_facility_currency_costs.py` | Facility build costs deducted correctly |
| `test_diplomacy_status.py` | Diplomatic relation status changes |
| `test_friend_requests.py` | Friend request/accept/refuse/remove flow |
| `test_mail.py` | Send, inbox, read, delete |
| `test_trade.py` | Create, accept, reject, cancel trade offers |
| `test_chat.py` | Global chat, DM channels |
| `test_public_nation_profile.py` | Public nation data visibility |
| `test_public_vacation_status.py` | Vacation mode visibility |
| `test_map_gen.py` | Map generation correctness |
| `test_pending_fleets.py` | Fleet pending-at-mine endpoint |
| `test_tick_event_log.py` | Event log entries after tick |
| `test_raid_resource_log.py` | Raid resource log correctness |
| `test_rename_cooldown.py` | Territory rename cooldown |
| `test_tutorial.py` | Tutorial step progression and rewards |

---

## Feature-to-File Quick Reference

| Feature | Backend | Frontend |
|---|---|---|
| Auth / sessions | `routers/auth.py`, `core/security.py` | `pages/Login.jsx`, `pages/Register.jsx`, `context/AuthContext.jsx` |
| Nation creation | `routers/nations.py` POST `` | `pages/NationCreate.jsx` |
| Resource production | `tasks/tick.py` (resource generation section), `services/territory_yield.py` | `pages/Economy.jsx`, `pages/Home.jsx` |
| Facility build/demolish | `routers/facilities.py` | `pages/Facilities.jsx` |
| Fleet combat | `tasks/tick.py` (engaged fleet section), `services/combat.py`, `routers/military.py` | `pages/Military.jsx` |
| Fleet dispatch | `routers/military.py` POST `/fleets/send` | `pages/Military.jsx`, `pages/MapView.jsx` |
| Occupation window | `tasks/tick.py` (occupation window section), `routers/military.py` POST `/fleets/{id}/occupy` | `pages/Military.jsx` |
| Dissent system | `tasks/tick.py` (dissent update section), `services/dissent.py`, `constants.py` | `pages/Economy.jsx` (per-territory table) |
| War declaration | `routers/diplomacy.py` POST `/war` | `pages/Diplomacy.jsx` |
| Lopsided war | `routers/diplomacy.py` (is_lopsided check), `services/power.py`, `constants.py` | — |
| Probe dispatch/scan | `routers/probes.py`, `tasks/tick.py` (probe movement section) | `pages/Probes.jsx`, `pages/MapView.jsx` |
| Probe marketplace | `routers/probe_market.py`, `models/probe_market.py` | `pages/ProbeMarket.jsx` |
| Colonization | `routers/military.py` POST `/colony-ships/{id}/send` + `/claim` | `pages/Military.jsx` |
| Vacation mode | `routers/nations.py` POST `/me/vacation/enter` + `/exit` | `pages/Home.jsx` |
| Diplomacy flags | `routers/diplomacy.py` PUT `/{id}` | `pages/Diplomacy.jsx` |
| Trade | `routers/trade.py` | `pages/Trade.jsx` |
| Mail | `routers/mail.py` | `pages/Mail.jsx` |
| Chat | `routers/chat.py` | `components/ChatWindow.jsx` |
| Event log | `routers/events.py`, `tasks/tick.py` (resource log section) | `pages/EventLog.jsx` |
| Notifications (badges + browser) | `routers/notifications.py` | `components/Layout.jsx` |
| Map display | `routers/territories.py` | `pages/MapView.jsx` |
| Tutorial | `routers/tutorial.py`, `services/tutorial.py` | `components/TutorialPanel.jsx` |
| Game constants | `constants.py` | — |
| Tick loop | `tasks/tick.py` | — |
