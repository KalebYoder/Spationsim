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
- Holding fleet attrition: `max(1, round(unit_count × HOLDING_ATTRITION_RATE))` losses per tick; rate = 2.5%/tick (`HOLDING_ATTRITION_RATE = 0.025` in `constants.py`); fleet deleted at zero with event logged
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

### Defender Counter-Attack System (designed 2026-06-07)

*Full design review in game-expert session. Implementation not yet started.*

**Mechanic 1 — Attacker opt-in per tick (hold-by-default)**

`post_battle_choice` window expiry now sets fleet status to `holding` rather than re-engaging automatically. The attacker must explicitly choose `engage` each tick to trigger combat. Default inaction = hold. This aligns with the core design principle (inaction never produces maximum harm) and matches CyberNations / P&W attacker-initiative model.

Implication: this makes the defender sortie mechanic non-optional. Without sortie, a holding fleet causes +6 dissent/tick while the attacker has zero incentive to ever commit to combat again. Attrition (2.5%/tick) is the only check, and a 100-unit fleet lasts ~40 ticks (~80 hours).

**Mechanic 2 — Defender sortie**

A defender can manually initiate combat against any enemy fleet in `holding` or `occupying` status at their territory. Sortie forces the fleet from its current status to `engaged` and combat fires that tick (following the one-combat-per-tick rule).

Sortie cooldown: once per 2 ticks (4 hours) per territory. Prevents online-availability arms race where a player who checks every 2 hours has a structural advantage over one who checks every 4–6 hours. If the design target is to avoid cooldown complexity in beta, implement sortie as auto-firing once per tick instead — removes the per-session advantage while keeping the defensive pressure.

Sortie while attacker is in `post_battle_choice`: sortie does not fire immediately. It queues for the next tick. If the attacker fleet is still present and has not yet chosen `engage`, the queued sortie fires. UI must communicate this ("Sortie queued — fires next tick if fleet is still present") rather than silently failing.

**Mechanic 3 — Defender auto-rout on defender win**

When a combat round produces more attacker losses than defender losses (defender structural win), an automatic "diminished rout" bonus fires: `bonus_attacker_losses = max(0, round(attacker_losses × DEFENDER_AUTO_ROUT_FRACTION))`.

`DEFENDER_AUTO_ROUT_FRACTION = 0.50` — 50% of attacker losses from that round, as additional attacker losses applied immediately. Rationale: 25% is too marginal to be meaningful. 50% brings the effective exchange rate toward the CyberNations home-ground defense standard without stacking an impossible barrier on top of the 1.5× multiplier.

Trigger condition: auto-rout fires only when the attacker also took nonzero losses in the combat round. If the attacker took zero losses (overwhelming force, defender dealt nothing), auto-rout does not fire. This prevents auto-rout from triggering on completely uncontested situations and limits it to competitive fights where the defender's structural advantage is actually in play.

No `post_battle_choice` window for defenders. Defenders get no Raid / Rout / Raze options. Auto-rout fires unconditionally on trigger — no player action required. This is intentional: the defender cannot predict or control when combat fires (the attacker initiates), so the defender's reward must not require the defender to be online.

**Mechanic 4 — One combat per tick, attacker initiative**

If both attacker choose `engage` AND a defender sortie is queued for the same tick, only one combat fires. Attacker initiative takes precedence: the attacker engage is processed, the sortie is consumed (not double-fired next tick).

**Attacker Rout for reference**: `bonus_damage = max(0, int(defender_losses × 0.25))` (25% of last-round defender losses). Attacker full Rout < Defender auto-rout (50% of attacker losses) — this is intentional. The attacker has agency (choice of when to press), the defender has structural advantage (automatic, stronger counter). The asymmetry is: attacker controls timing, defender controls outcome quality when they win.

**Raid cap — elevated priority**: the new attacker opt-in model makes Raid cycling more deliberate and predictable (engage → win → Raid → hold → next tick engage). The uncapped Raid issue flagged in the spec's Known Open Issues must be resolved before this mechanic ships. A per-Raid cap of 10% of the defender's current national stockpile (matching CyberNations / P&W precedent) is the recommended starting point. Add `RAID_CAP_FRACTION = 0.10` to constants.py.

**Constants to add to constants.py:**
- `DEFENDER_AUTO_ROUT_FRACTION = 0.50`
- `RAID_CAP_FRACTION = 0.10`

**Fleet statuses affected:**
- `post_battle_choice` expiry → `holding` (was: `engaged`)
- New attacker action: `POST /fleets/{id}/engage` sets `holding` → `engaged` (triggers combat next tick)
- New defender action: `POST /territories/{id}/sortie` sets enemy `holding`/`occupying` fleet → `engaged` (subject to cooldown)


## What's Still To Do

### Remaining Feature Work

**Exploration (Phase 3)**
- [x] Information selling — probe data marketplace; players list and purchase others' probe data; seller retains data; UI shows data age and whether the target is already colonized at time of purchase

**Combat (Phase 4)**
- ~~Pre-engagement skirmishing during `pending_confirmation`~~ — removed; the 4-hour confirmation window is intentionally low-pressure and should not punish players for taking time to decide. Reconsidering only if lurking at the confirmation stage becomes an abuse vector.
- [x] Dissent system implementation — table, tick logic, production/growth penalties, decay, Propaganda Office facility, conquest-set behavior
- [x] War declaration lopsided-war dissent multiplier — implement 1.5× aggressor dissent accumulation when attacker military strength > 3× defender military strength at time of declaration; threshold is a beta-tuning knob, bring to veteran players
- [x] Propaganda Office decay cap during active aggression — reduce PO decay bonus from +2 to +1 on aggressor's territories for the duration of any war they declared; prevents large nations from insulating themselves from dissent while simultaneously running aggressive wars
- [x] Occupation window — new `occupying` fleet status set when last defender fleet is destroyed and territory becomes uncontested; `occupation_expires_at` stored on fleet row; tick promotes expired occupying fleets to withdrawn (fleet recalled); window cancelled if enemy arrives; `POST /fleets/{id}/occupy` endpoint triggers instant conquest + dissent-set-to-60 + upkeep start
- [x] Move dissent-set-to-60 from defender-defeat event to occupy action — `conquer_territory` endpoint renamed to `occupy_territory` (`POST /fleets/{id}/occupy`); dissent-60 remains in that endpoint; frontend Conquer button renamed to Occupy
- [x] Home-territory defense multiplier — apply `HOME_TERRITORY_DEFENSE_MULTIPLIER` (= 1.5) to defender effective unit count when combat occurs on a colonized territory owned by the defender; implementation: `defender_effective = defender_count × HOME_TERRITORY_DEFENSE_MULTIPLIER` before the damage formula runs; void-space and unclaimed territory fights are unaffected; multiplier applies to the mobile combat phase only (does not stack with future stationary defenses, which use a separate pre-engagement phase)

**Player Interaction (Phase 5)**
- [x] Probe data public marketplace — a listing board where players post probe data for sale at a fixed price; any nation can browse and purchase; seller retains data (`GET/POST/DELETE /api/probe-market`, `POST /api/probe-market/{id}/buy`, `ProbeMarket.jsx`)

**Alpha Test (Phase 6)**
- [ ] Invite veteran player testers (closed beta)
- [ ] Publish public roadmap
- [ ] Establish feedback collection process

### Known Open Issues

**Balance**
- **Population growth rate** — currently 1%/tick. Territories fill to their richness-based cap quickly at low populations. Monitor during beta; may need to reduce to 0.1–0.5% if population becomes a non-constraint too quickly.
- **Holding fleet attrition rate** — currently `max(1, round(unit_count × 0.025))` (2.5%/tick, min 1). A 100-unit fleet lasts ~40 ticks (~80 hours). Monitor during beta; reduce if fleets disappear before players can act, increase if lurking remains a problem.
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

- **Dissent: attacker-side penalty?** Should the attacker also accumulate +2/tick dissent on their home territories for the duration of a war? Argument for: prolonged aggressive wars should have internal political cost. Argument against: in a 20–50 player beta, making aggression too costly reduces conflict below the threshold needed to test the war system. Recommendation: defer to post-beta unless veteran feedback says wars last too long. *(Current behavior: aggressors already accumulate +3/tick dissent on all owned territories — `DISSENT_WAR_AGGRESSOR = 3` in constants.py, applied in tick.py. The "Attacker-Side Dissent" section of the dissent spec is an outdated artifact that predates this. The live question is whether to keep, tune, or remove the +3/tick penalty.)* Note: the current production penalty curve `t = max(0, (d−25)/75)` is flat from 0–25 dissent and reaches 50% loss only at d=75, meaning a short war (24h minimum = 12 ticks at +3/tick = 36 dissent) barely enters the penalized zone. Consider shifting the anchor so 50% production loss occurs at d=50 rather than d=75 — formula change: `t = max(0, (d−10)/40)`. This makes the soft deterrent bite in wars of realistic length without capping aggression entirely. Bring to beta before deciding.
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
- ~~**Occupation drain: what fraction of territory production should the attacker steal?**~~ *(Resolved — passive occupation drain removed entirely. Replaced by post-battle choice: Raid steals a random amount scaled to fleet firepower; Rout does bonus damage to defenders; Raze is deferred. See Raze infrastructure scoring scale below.)*
- ~~**Occupation drain: should drain scale with occupying fleet size?**~~ *(Resolved — passive occupation drain removed. Fleet size now affects Raid output directly via the firepower formula.)*
- **Raze: infrastructure scoring scale.** Raze is stubbed out pending a decision on how to quantify "infrastructure value" for a territory. The intent is that Raze deals damage to planetary infrastructure proportional to the attacking fleet's firepower relative to the territory's total infrastructure score. Open questions: (1) How is infrastructure score computed — flat count, weighted by facility type (shipyard vs. mine), or weighted by level? (2) What does "damage" mean — does it reduce facility level, destroy the facility outright, or apply a temporary production debuff? (3) Should Raze consume attacker resources (fuel, ammunition proxy) or be free? Decide before implementing.
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
| Holding fleet attrition | `max(1, round(unit_count × HOLDING_ATTRITION_RATE))` losses per tick; `HOLDING_ATTRITION_RATE = 0.025` | 2.5%/tick with minimum 1 unit/tick. A 100-unit fleet lasts ~40 ticks (~80 hours) under contested holding. Replaces the zero-cost lurking mechanic. Fleet deleted at 0 with events logged. Monitor rate during beta; reduce if fleets disappear before players can act, increase if lurking remains a problem. Constant defined in `constants.py`. |
| Fleet fuel upkeep | 1 fuel/tick per fighter not docked on own territory | "Docked" = stationed on a territory owned by that nation. All other fleet statuses and stationed fleets on foreign/unclaimed territory pay upkeep. Creates ongoing fuel drain for sustained military projection. |
| Power metrics | Military strength (1 per fighter) + industrial strength (mine=1, refinery=1, shipyard=2) | Computed at query time, not stored. Visible to all on nation profiles; visible to self on home page. Provides a competitive reference frame and a rough matchmaking signal. |
| Friends system | Separate from diplomacy; friend_pending blocks planet dispatch | Friend requests use the diplomacy table (status: friend_pending/friendly). A nation in friend_pending or friendly status cannot have fleets dispatched to their planets, treating them like neutral for combat purposes. |
| Dissent system | Per-territory integer 0–100; aggressor/defender asymmetry; fleet-presence penalties; Propaganda Office resistance; continuous production penalty curve | Sources: aggressor +3/tick all territories, defender +2/tick all territories, holding fleet +6, engaged fleet +10, instant set to 60 on occupy (formal annexation), not on defender defeat. Decay: −3 peace, −2 war (no occupation), 0 occupied. Propaganda Office: +2 decay normally, +3 under occupation. Production modifier: `max(0, 1 − t^1.71)` where `t = max(0, (d−25)/75)` — 50% loss at d=75, complete at d=100. Population growth suppression deferred. Notification events at thresholds 25/50/75/100. `declared_by` field on diplomacy row records aggressor. Does not rise during vacation mode. |
| Population consumption at fighter manufacture | Deducted from territory `current` population only; the richness-based cap (`50 × (mineral_richness + fuel_richness)`) is never modified | Population regrows naturally each tick toward the cap. Fighter deaths do not restore population — pop spent at manufacture is permanently gone if the unit is destroyed in combat. This resolves the open question "does population die permanently?" — yes, at the point of manufacture, but the territory's growth capacity is unaffected so the nation recovers over time. |
| Territory logistics upkeep | Quadratic fuel cost on territory count: `k × N(N+1)/2` fuel/tick, k=1 at beta start | Chosen to make empire growth logarithmic rather than linear: fuel income scales as N but logistics cost scales as N², creating a natural soft cap on expansion. The Nth territory costs N×k fuel/tick marginal cost. At k=1 a 20-territory empire pays 210 fuel/tick in logistics alone. k is stored as `LOGISTICS_FUEL_K` in constants.py and should be tuned during beta based on observed expansion rates. Do not change k without reviewing fuel production rates (5–10 fuel/tick per refinery on normal territories). |
| Territory count currency upkeep | Superlinear currency cost: `k × N²` per tick, k=10 at beta start | Marginal cost of the Nth territory = k(2N−1). Optimal expansion stops at N* ≈ I/(2k) where I = currency income per territory. At k=10: rim player (I≈150) optimal N*≈7, medium (I≈300) N*≈15, dense core (I≈600) N*≈30. Rewards deep development (higher I per territory → larger profitable empire) over pure sprawl. Creates the intended progression: develop territories to unlock the right to hold more of them. k stored as `TERRITORY_UPKEEP_K` in constants.py. See Open Questions for rim-player monitoring note. |
| Peace mechanic | Bilateral only — wars end exclusively through a mutually confirmed peace trade | Unilateral peace removed. Peace can be packaged with resource payments and territory transfers in the trade window, allowing structured negotiated settlements (reparations, cessions, white peace). The 24h minimum war duration does not apply to bilateral peace agreements. |
| War declaration power-range gate | No hard power-range gate; adjacency + dissent scaling is the primary deterrent combo | Hard gates get gamed by stat-sandbagging (CyberNations precedent). Adjacency requirement already encodes a geographic power constraint: projecting force to rim players requires building a column of colonies that is itself vulnerable and expensive. Dissent serves as a secondary cost layer for sustained predatory behavior, not as a complete single-war deterrent. Two dissent tuning changes are queued: (1) lopsided-war multiplier of 1.5× aggressor dissent when attacker military strength > 3× defender at war declaration time; (2) Propaganda Office decay bonus capped at +1 (from +2) on aggressor territories for the duration of any war they declared. The 3× threshold was chosen over 2× because a 2:1 unit gap is within normal variance between players of different development stages — an older or more economically developed nation can easily have 2× units without being predatory. A 3:1 ratio implies a clearly dominant position that is unlikely to produce a competitive fight. The threshold is still a beta-tuning knob; lower to 2× if predatory attacks at 2:1 ratios are observed during play. |
| Facility caps | Population is the only cap — stacking one facility type at the expense of others is a valid strategic choice; balance via population costs rather than hard slot limits. | |
| Combat damage model | Shields as flat damage reduction; `net_damage = max(0, firing × FP − target × Shields)`; `losses = max(1, round(net / Structural_Integrity)) if net > 0 else 0` | Both sides fire simultaneously. Unit stat names: FP, Shields, Structural_Integrity (formerly FP, DEF, HP). DEF was dead code; renamed to Shields and wired into formula. A well-shielded fleet fully absorbs weak attacks. |
| Probe visibility scope | Probe_data (richness) recorded only at the destination; all other tiles on the probe's path record probe_visibility (existence only) | Removes the radius-2 scanning behaviour that gave players richness data for tiles surrounding every step. The probe is a targeted instrument, not a scanner. Path tiles appear on the map as "tile exists" without stats. |
| Fleet dispatch default | Dispatch defaults to the full stationed fleet; entering fewer units splits the fleet, leaving the remainder stationed | The MapView quantity input defaults to max; shows "splits fleet" label and remaining-behind count when the user reduces it. Arriving fleets auto-merge into any existing stationed fleet at the destination. |
| Occupation window | 6-tick (12-hour) forced-choice after last defender fleet destroyed and territory uncontested; default = withdraw | Attacker fleet enters `occupying` status. Attacker chooses occupy (instant conquest, upkeep begins, dissent set to 60) or withdraw (fleet recalled). Window cancelled if enemy units arrive during the window — fleet reverts to `holding`. Default on expiry = withdraw (inaction = safe). Early occupy or early withdraw both allowed. Dissent set to 60 fires on occupy action only — not when defenders are destroyed — to prevent repeated defeat-and-withdraw as a dissent weapon. Fleet row stores `occupation_expires_at`. Endpoints: `POST /fleets/{id}/occupy` and `POST /fleets/{id}/withdraw` (withdraw already exists; occupy is new). |
| Home-territory defense multiplier | `HOME_TERRITORY_DEFENSE_MULTIPLIER = 1.5`; defender effective count multiplied by 1.5 when fighting on their own colonized territory | Resolves the symmetric-attrition problem: equal forces no longer annihilate each other symmetrically — the attacker needs ~1.5× numerical superiority to achieve casualty parity on a defended planet. Implementation: `defender_effective = defender_count × HOME_TERRITORY_DEFENSE_MULTIPLIER` substituted into the damage formula before `net_damage` is computed; attacker fires against `defender_effective`, defender fires against the literal attacker count. Applies to mobile combat phase only. Does NOT apply to: void-space fleet engagements, combat on unclaimed territory, combat on territory owned by neither combatant. Does NOT interact with future stationary defenses, which use the pre-engagement phase model and fire before mobile combat begins. Constant stored in `constants.py` as a beta tuning knob. Value 1.5 chosen over 2.0: a 2× multiplier would require 2:1 attacker superiority to break even — the same 2:1 ratio the lopsided-war dissent gate already treats as normal variance, creating contradictory signals. 1.5× sets a meaningful but not prohibitive bar, analogous to P&W's Fortify policy (+25% attacker casualties), CyberNations' infrastructure-as-soldiers defender bonus, and Tribal Wars' wall multiplier system — all of which create a moderate defender edge without making offense structurally impossible. Does not introduce turtling as a dominant strategy because: (1) the adjacency requirement means attacking is already costly in logistics and territory commitment; (2) dissent still accumulates on both sides during prolonged conflict; (3) the attacker chooses when to engage and can withdraw — the multiplier raises the bar for conquest but does not guarantee defender survival against a determined 1.5×+ force. |
| Attacker opt-in per tick (hold-by-default) | `post_battle_choice` expiry → `holding`; attacker must explicitly choose `engage` to trigger combat each tick | Matches CyberNations/P&W attacker-initiative model. Aligns with "inaction never produces maximum harm." Makes defender sortie mechanic non-optional rather than nice-to-have. New endpoint: `POST /fleets/{id}/engage` (holding → engaged). |
| Defender sortie | Manual defender action forcing enemy `holding`/`occupying` fleet to `engaged`; combat fires that tick. Cooldown: once per 2 ticks per territory. If attacker is in `post_battle_choice`, sortie queues for next tick. | Gives defender active recourse against indefinite lurk/bleed strategy. Cooldown prevents online-availability arms race. Genre precedent: CyberNations auto-fires defender responses; P&W allows independent defender attack actions. Auto-fire variant (no cooldown, auto per tick) acceptable if cooldown adds too much implementation complexity for beta. |
| Defender auto-rout | `DEFENDER_AUTO_ROUT_FRACTION = 0.50`; fires automatically when defender wins combat round (attacker losses > defender losses AND attacker took nonzero losses). Adds `round(attacker_losses × 0.50)` extra attacker losses. No player action required. | 50% chosen over 25%: 25% is too marginal to affect outcomes meaningfully. 50% brings effective exchange rate toward CyberNations home-ground defense standard. Trigger condition (nonzero attacker losses) prevents auto-rout from firing when the attacker brought overwhelming force and the defender dealt nothing. Defenders get no post_battle_choice window — auto reward is unconditional because defenders cannot control when combat fires. |
| Raid cap | `RAID_CAP_FRACTION = 0.10`; per-Raid steal capped at 10% of defender's current stockpile per resource | Elevated to required before shipping attacker opt-in system. Deliberate Raid cycling (engage → win → Raid → hold → repeat) is now a predictable strategy. 10% matches CyberNations and P&W loot caps. Prevents a single large fleet from zeroing a small nation's stockpile in one action. |

---

## Expert Review Notes

*Added 2026-05-29. Findings are grounded in code review of `backend/app/tasks/tick.py`, `backend/app/routers/military.py`, `backend/app/routers/diplomacy.py`, and `backend/app/constants.py` alongside the spec.*

---

### Best Practice Violations

~~**The `holding` fleet status conflates two distinct situations with incompatible mechanics.**~~ *(Fixed — attrition now only applies when the holding fleet's destination territory has stationed fleets belonging to a nation the holding fleet's nation is at war with. Holding on neutral, friendly, or unoccupied territory never triggers attrition. Remaining issue: the Active Operations UI does not yet surface attrition rate or projected time-to-zero — players still cannot see why their fleet is decaying without reading the event log.)*

**~~Colony ship reachability is not enforced at the endpoint level.~~** *(Fixed — `send_colony_ship` now runs `compute_reachable_ids` before dispatch, identical to fleet dispatch.)*

**~~Population deduction for fighter manufacture draws from all territories in descending-population order, not from the shipyard territory.~~** *(Fixed — manufacture now deducts from the shipyard territory's population only, and fails if that territory has insufficient unassigned population.)*

**Specified:** Fighter manufacture consumes population from the territory on which the shipyard is built. The quantity produced is limited by that territory's unassigned population (territory current population minus population assigned to facilities at that territory). Population is permanently consumed — fighter deaths do not restore it.

**~~The `conquer_territory` endpoint deletes all probe data for the captured territory but does not delete probe visibility entries.~~** *(Fixed — `ProbeVisibility` rows are now deleted alongside `ProbeData` and `ProbeDataAccess` on conquest.)*

**War declaration allows fleets already in transit to proceed unimpeded through the 2-tick grace period.** When a war is declared, a `war_pending` row is created and hostilities begin 4 hours later. However, fleets dispatched before declaration (in status `in_transit`) continue to travel during the grace period and will arrive at the enemy territory the moment `war` becomes active, potentially before the defender has received a tick notification. The spec says the grace period exists so defenders can "see the war declared notification and prepare" — a fleet that departs the same tick war is declared can arrive the same tick war becomes active, negating the grace period entirely for short distances. This is the open question about "defender repositioning during war declaration window" from the Open Questions section and is flagged there, but the code has no guard against it.

**~~*(2026-06-05)* The dissent tick loop reads `origin_territory` instead of `destination_territory` for `holding` and `engaged` fleets.~~** *(Fixed — `tick.py` now reads `fleet.destination_territory` for holding/engaged fleet-presence dissent. `origin_territory` is the attacker's launch point; `destination_territory` is the occupied territory.)* `tick.py` iterates over holding/engaged fleets and applies dissent to `fleet.origin_territory`. But `origin_territory` is the fleet's launch point. The territory the fleet is physically occupying is `destination_territory` — this is also what `conquer_territory` and `_send_fleet_home` use. The result: fleet-presence dissent penalties are being applied to the attacker's own launch planet rather than the defender's occupied territory. This is a silent correctness bug that inverts the entire fleet-presence mechanic.

**~~*(2026-06-05)* The `war_role` assignment in the tick is first-seen-wins across multiple simultaneous wars.~~** *(Fixed — `war_role: dict[int, str]` replaced with `war_dissent_delta: dict[int, int]` (summed contributions across all active wars) and `at_war: set[int]` (for decay-mode selection). A nation aggressor in one war and defender in another now correctly accumulates +3 +2 = +5/tick instead of whichever role appeared first.)* The tick builds a `war_role` dict keyed by nation ID; the first diplomacy row found for that nation sets its role for all dissent calculations. If Nation A declared war on B (aggressor) and C declared war on A (defender in a separate war), Nation A's role is determined by whichever row the query returns first. Multi-war scenarios — which are exactly the coalition-warfare situations that drive endgame politics in this genre — will accumulate dissent at the wrong rate. Fix: compute dissent contributions per war-pair, not per nation.

**~~*(2026-06-05)* The per-territory currency display on the Planets page excludes territory-count upkeep.~~** *(Fixed — the `GET /mine/territories/yields` endpoint computes `TERRITORY_UPKEEP_K × N` per territory (the per-territory share of the `k × N²` total), subtracts it from `currency_net_per_tick`, and exposes it as a separate `territory_upkeep_currency_per_tick` field. The Planets page displays it as a "Territory upkeep" line in the expanded panel.)* `compute_territory_yield()` returns `currency_net_per_tick` as income minus fighter upkeep only. The `TERRITORY_UPKEEP_K × N²` nation-level upkeep is computed separately in the tick and not reflected in the per-territory breakdown. A player will see green net-positive numbers on every territory while their national stockpile is declining. CyberNations showed nation-level net income as a single summary; OGame showed explicit running costs per building. Either pattern works; the current hybrid (territory-level income, nation-level costs, no reconciliation) creates a misleading picture.

**~~*(2026-06-05)* Probe detection fires an event for every territory a probe transits, every tick it is in transit.~~** *(Fixed — `probe.last_detected_nation_id` tracks the last nation to detect the probe; the event only fires when that value differs from the current territory owner. After firing it is set to the owner's nation ID, suppressing repeats. Cleared back to `None` when the probe re-enters friendly space.)* A probe crossing six owned territories fires six `enemy_probe_detected` events — one per tile per tick. In a dense beta where multiple probes from different scouts are crossing the same territory simultaneously, the event log will produce noise that buries actionable information. The design intent is early-warning; the implementation is spam. First-detection-only (one event per probe per territory, not one per tick) is the correct behavior.

**~~*(2026-06-05)* Raid resource transfers fire to the events table but not to `resource_log`.~~** *(Fixed — `raid_fleet` now inserts two `ResourceLog` rows on success: a positive entry for the attacker and a negative entry for the defender, both timestamped to `now`. Covered by `tests/test_raid_resource_log.py`.)* The resource log records production gains but not combat losses. The events table and the resource_log serve different query patterns — both need raid entries for the offline recap to be coherent.

**~~*(2026-06-06)* Facility construction population check uses nation-wide unassigned pop, not per-territory unassigned pop.~~** *(Resolved — `build_facility` now queries `TerritoryPopulation.current` for the target territory only and subtracts only that territory's assigned pop via `_territory_assigned_pop(territory_id)`. Nation-wide `_assigned_pop` helper removed.)* `facilities.py` lines 116–128 sum total population and total assigned population across all of the nation's territories, then compare the difference against the facility's pop cost. This means a player can queue a mine at Territory A (which has 0 unassigned pop) as long as Territory B has spare pop somewhere in the empire. The population reservation is effectively fictitious — the pop will never physically move to Territory A to staff the facility. Fighter manufacture (`military.py` lines 219–229) correctly checks per-territory unassigned population against the shipyard territory. Facilities should use the same per-territory check: sum `Infrastructure.population_assigned` only for facilities at the same `territory_id`, not nation-wide. This is a silent inconsistency that will surface during beta when players wonder why a facility they built isn't producing while their population numbers look fine.

**~~*(2026-06-06)* There is no way to cancel a facility that is `under_construction`.~~** *(Resolved — `DELETE /api/facilities/{id}/cancel` added; cancellation is allowed only while `status == "under_construction"` and issues a full resource refund. Cancel button surfaced in the frontend facility list. Covered by `tests/test_cancel_construction.py`.)* `demolish_facility` in `facilities.py` line 185 explicitly rejects demolition requests for anything other than `status == "active"`. Once a facility is queued, the resources are spent and there is no cancellation path until the facility completes (1–2 ticks later). An accidental double-queue of the same facility type, or a mind change during the 2-tick shipyard build, has no recovery option. OGame and P&W both allow cancelling queued construction with a full resource refund. The consequence at beta scale is limited (20–50 players, all veterans), but the absence of a cancel path is a design antipattern for asynchronous games where decisions are made between sessions.

**~~*(2026-06-06)* `is_lopsided` is never set when war is declared through the `PUT /api/diplomacy/{target_nation_id}` endpoint.~~** *(Resolved — added the same `military_strength` ratio check to the `war` branch of `set_relation`. Both endpoints now compute and store `is_lopsided` identically.)* `diplomacy.py` has two paths that create a `war_pending` row: the dedicated `POST /api/diplomacy/war` endpoint (line 194 sets `row.is_lopsided`) and the general `PUT /api/diplomacy/{target_nation_id}` endpoint (`set_relation`, lines 292–312 do not set `is_lopsided`). Any war declared through the PUT path will always have `is_lopsided = False` regardless of the actual military ratio. The lopsided-war dissent multiplier (`DISSENT_LOPSIDED_MULTIPLIER = 1.5`) will silently never activate for wars declared via that route. Both endpoints should call the same `is_lopsided` computation or the PUT path should be removed as a war-declaration mechanism.

**~~*(2026-06-06)* The `post_battle_choice` window expiry causes the fleet to fight a second combat round in the same tick.~~** *(Resolved — expiry promotion block moved to after the engaged-fleet loop; fleets become `engaged` at end of tick and resume combat on the next tick.)* `tick.py` lines 514–522 promote expired `post_battle_choice` fleets to `engaged` status. Lines 525–628 then process all `engaged` fleets, which includes those just promoted. This means a fleet whose post-battle-choice window expires gets no combat round deducted during the window tick but then immediately fights combat the same tick the window expires — effectively experiencing two combat rounds in one tick from the player's perspective (the choice window closes, then combat resolves before the next tick). The intent is that expiry should result in the fleet simply resuming combat on the *next* tick, not the current one. The fix is to promote expired post-battle-choice fleets to `engaged` at the END of the tick loop, after the engaged-fleet processing block, or to set a flag so they are skipped in the current tick's combat pass.

---

### Missing Features

**~~No new player starting tutorial or guided first actions.~~** *(Fixed — a full multi-step tutorial system is implemented: `TutorialState` model, `GET /api/tutorial/`, step-completion endpoints, per-step rewards, and frontend highlighting. See the Tutorial Planning section of this spec for the full design.)*  Veteran players testing a closed beta will orient themselves, but the starting state (100 minerals, 100 fuel, 2000¤, 100 pop, one territory) gives no in-game signal about what to build first. OGame and Ikariam both have guided first-action queues. Without this, early beta feedback will include confusion about the correct opening sequence (mine → shipyard → fighters vs. mine → probe factory → exploration), which is actually a meaningful strategic choice the game should surface, not obscure.

**~~No territory-level resource production breakdown accessible from the Military or Planets pages.~~** *(Partially fixed — the Planets page expanded panel now shows a Production / Tick section with per-territory gains (minerals, fuel, territory income) and costs (fighter upkeep), sourced from the existing `GET /api/nations/mine/territories/yields` endpoint. The Military page still does not show a per-territory breakdown of which territories are funding fleet upkeep; that cross-reference remains absent.)*

**~~No combat log accessible to third parties.~~** *(Fixed — `GET /api/nations/{nation_id}/wars` lists all wars for any nation (requires login), and `GET /api/nations/{nation_id}/wars/{opponent_id}/log` returns the full `combat_round` and `resources_drained_by_occupation` event history between any two nations, enriched with territory names. The public nation profile page now shows a "War History" section with a dropdown of past wars and "View Log →" links to a dedicated combat log page at `/nations/:id/wars/:opponentId`.)*

**~~No player-facing dissent UI.~~** *(Fixed — dissent system is fully implemented. Territory detail view shows a dissent bar and production penalty when dissent > 0. Event log shows threshold-crossing events (25/50/75/100, rising and falling) in amber/teal. `GET /api/nations/mine/territories/yields` returns `dissent` and `dissent_modifier`. `GET /api/nations/mine/territories` returns `dissent` per territory.)*

**~~No public probe data marketplace.~~** *(Fixed — `GET/POST/DELETE /api/probe-market` and `POST /api/probe-market/{id}/buy` implement the full public storefront. Buyers see richness, colonization status, reachability, and seller name without coordinates until purchase. `ProbeMarket.jsx` is the frontend page. Seller retains data after sale.)*

**~~*(2026-06-05)* No minimum war duration or post-peace redeclaration cooldown.~~** *(Fixed — `diplomacy.py` enforces a `peace_until` timestamp on the diplomacy row; re-declaring war while `peace_until > now` returns 409 with the remaining tick count.)*  The spec mentions a 24h minimum duration but it is unimplemented. Without it, a declare → strike → forced peace → repeat cycle is unchecked. The genre standard fix is a post-peace cooldown (48–72h before the same pair can re-declare). Without alliances in beta, there is no defensive pact mechanism, making serial harassment against a single target unusually cheap.

**~~*(2026-06-05)* No aggregated war cost summary.~~** *(Fixed — `GET /{nation_id}/wars/{opponent_id}/status` aggregates fighters lost, resources drained, and war cost in minerals/fuel/currency across all combat events for the war pair.)* Players have no view of total fighters lost, resources drained, or dissent hours accumulated per war. The combat log endpoint exists but there is no UI page that aggregates war economics. Veteran players expect this for peace negotiation — they cannot make an informed bilateral peace decision without knowing what the war has cost both sides.

**~~*(2026-06-05)* No nation search or player directory.~~** *(Fixed — `GET /api/nations/list` returns all nations ordered by name; a `NationSearch` frontend component exists in `src/components/NationSearch.jsx`.)* There is no way to find another nation by name. Players coordinating via Discord (the intended alliance mechanism in beta) cannot find each other's nations in-game without posting coordinates or nation IDs externally. A simple name-search endpoint and directory page is a first-session expectation for any veteran player.

***(2026-06-05)* No notification on fleet arrival at an enemy territory.** The confirmation window protection only works if players see the alert. Do not email on every fleet arrival during war — veteran players will unsubscribe. Three-layer plan: (1) ~~**In-game alert badge**~~ *(Done — red badge on Military sidebar nav item, polled every 45 s via `GET /api/notifications` `threat_count`; endpoint `GET /api/military/fleets/pending-at-mine` supplies the defender view.)* (2) ~~**Browser notifications (Notification API)**~~ *(Done — `fleet_pending_action` event added to `GET /api/notifications`; `Layout.jsx` polls and fires a native `Notification` when pending fleet counts increase; bell icon in sidebar footer requests permission. Fires while the page is open in the browser. Full Web Push API — server-initiated, fires when browser is closed — is not yet implemented.)* (3) **Email** only for account events and post-mortem when a window expired unresolved; user opt-in, default off. Not yet implemented.

**~~*(2026-06-05)* No endpoint for the defender to query pending-confirmation fleets at their own territories.~~** *(Fixed — `GET /api/military/fleets/pending-at-mine` returns all `pending_confirmation` fleets at the player's territories, including fleet size and expiry time. Covered by `tests/test_pending_fleets.py`.)* The spec says the attacking fleet is "visible to the defender during the confirmation window," but there is no API endpoint that returns fleets currently in `pending_confirmation` at territories the player owns. The defender knows a fleet exists from the event, but cannot query fleet size on demand.

***(2026-06-06)* Email notifications are not yet implemented.** Layer 3 — opt-in email for account events and expired windows — is unimplemented. Web Push API (server-initiated, fires when browser is closed) is intentionally out of scope: players who want alerts will keep the game open; mobile push notifications would come through a native app if one is ever built. Email remains the only deferred layer.

**~~*(2026-06-06)* The `is_colonized` flag on `Territory` is semantically overloaded, causing a confusing UX failure for colony ship dispatch.~~** *(Resolved — `is_colonized` renamed to `is_owned` and `colonized_at` to `owned_at` across all 39 affected files (models, routers, tick, tests, frontend). "Colonized" is now a derived concept: `is_owned AND territory_population > 0`. Colony ships may travel to any unclaimed territory and claim it on arrival in `tick.py`; void and enemy-owned territory remain blocked. The UI and `Probes.jsx` use the explicit `is_owned && territory_population > 0` check wherever population presence matters. Migration `017_rename_is_colonized.sql` applied to prod DB.)* A fleet claiming an unclaimed territory sets `is_colonized = True` and `nation_id = <player>`. The territory is now owned. However, `send_colony_ship` at `military.py` line 979 gates dispatch on `dest.is_colonized == True and dest.nation_id == nation.id`, which would pass — but wait: `claim_territory` at line 789 sets `is_colonized = True`. So the colony ship CAN be sent there. But the endpoint description says colony ships can only travel to "your own colonized territories" — and in practice, a fleet-claimed territory has no population row, so unloading there will work but the territory will have 0 pop until unload. The more precise issue: the UI and docs call this territory "claimed" (by fleet) vs "colonized" (populated), but `is_colonized` is `True` in both cases. Players reading the Planets page or tutorial prompts that use "colonized" may not understand they still need to unload a colony ship to staff facilities. This is a documentation and UI labeling issue more than a code bug, but it will cause repeated confusion in beta. Consider renaming the flag to `is_owned` or surfacing a separate `is_populated` state in the UI.

---

### Balance Issues

**~~Currency income is linear with territory count but fighter upkeep is linear with fighter count, creating a perverse incentive.~~** *(Resolved — currency income is now facility-based (`(mine_count + refinery_count) × CURRENCY_INCOME_PER_FACILITY`), not a flat per-territory reward. A superlinear territory-count upkeep (`TERRITORY_UPKEEP_K × N²`) acts as the missing currency brake on expansion. See the Territory Count Currency Upkeep section of the spec.)* 500¤/tick per active territory, 2¤/tick per fighter. A 5-territory nation earns 2,500¤/tick and can sustain 1,250 fighters on currency alone before considering other costs. The logistics fuel cost (quadratic with territory count) constrains expansion via fuel, but currency has no equivalent brake. Infrastructure maintenance costs are post-beta — without them, large empires accumulate currency faster than small ones with no counterbalancing pressure. This means the dominant first-mover advantage is to colonize as many territories as possible early to build a currency surplus that sustains a fighter force small nations cannot match.

**~~Combat loss formula produces near-symmetrical attrition, making offensive war too costly.~~** *(Fixed — `HOME_TERRITORY_DEFENSE_MULTIPLIER = 1.5` applied to defender effective unit count when combat occurs on the defender's own colonized territory. Attacker needs ~1.5× numerical superiority to achieve casualty parity. Void-space and unclaimed territory fights are unaffected. See Decisions Log for full rationale and scope constraints.)* With FP 2, Shields 1, SI 5, both attacker and defender lose `max(1, round((opponent × 2 - self × 1) / 5))` per tick when forces are roughly equal. Equal-sized forces annihilate each other in roughly 2–3 ticks. An attacker who travels several ticks to reach an enemy territory then fights to mutual destruction gains nothing — the territory is conquered with a badly depleted force that then immediately starts paying holding attrition. CyberNations used a ~3:1 attacker-to-defender ratio requirement to overcome ground defenses; P&W's resistance system means defenders absorb attacks without losing units until resistance hits zero. The current symmetric formula means conquest is only viable with overwhelming numerical superiority. The dissent system (when implemented) will add production pressure on both sides but does not change the fundamental combat exchange rate. A home-territory multiplier (e.g., defender effective count × 1.5) would make defense meaningful without changing the formula or unit stats.

**~~Holding fleet attrition applies equally regardless of which territory the fleet is holding at.~~** *(Fixed — attrition now only fires when the holding fleet's destination territory also has a stationed fleet from a nation that fleet is currently at war with. A fleet holding at a friendly border, neutral space, or post-ceasefire with no enemy units present takes zero attrition. The silent decay problem for fleets caught in limbo during war resolution is resolved. Implementation: `tick.py` builds a `stationed_at` map (territory → set of nation_ids with stationed fleets) and `at_war_with` map (nation_id → set of enemy nation_ids), then skips attrition if the intersection is empty.)* `holding` status applies both to fleets whose confirmation window expired at an enemy planet and to fleets that transition from `engaged` when a territory becomes uncontested. Attrition is 1%/tick in both cases. The spec says the default standing order is `hold` — a player who forgets to set `recall` loses 1%/tick silently until they check the event log. A 200-fighter fleet in holding at a friendly border (e.g., post-ceasefire, awaiting recall order) loses 2 fighters per tick, ~72 fighters in the 36 ticks of a weekend absence. The mechanic is correct for genuine occupation scenarios; it is punishing for fleets caught in limbo during war resolution. Consider only applying attrition to fleets holding on enemy-owned territory, not to fleets holding on unclaimed or formerly-enemy territory after ownership changes.

**~~Resource drain targets nation stockpile at a flat 5% regardless of attacker fleet size.~~** *(Fixed — drain is now bounded by the occupied territory's actual per-tick production. The occupier intercepts what the planet generates rather than raiding the national stockpile. A territory with no active facilities produces nothing to drain. See Open Questions for fraction and fleet-size scaling decisions.)*

**~~Demolish refund is 25% of mineral/fuel cost but does not refund currency.~~** *(Fixed — `tick.py` applies `DEMOLISH_REFUND_FRACTION` to all three resource components including currency. Mine demolish returns 125¤, refinery 125¤, shipyard 500¤.)*

**~~*(2026-06-05)* Population growth rounds to zero for territories under 50 pop — permanent trap.~~** *(Fixed — `tick.py` uses `max(1, round(pop × POPULATION_GROWTH_RATE))`, guaranteeing at least 1 growth per tick when below cap.)* Growth is `min(round(pop × 0.01), cap − pop)`. `round(49 × 0.01) = round(0.49) = 0`. Any territory with fewer than 50 pop grows at exactly zero per tick. A player who staffs their first territory heavily (mine + refinery + shipyard = 39 pop assigned from a starting 100) and then loses population to fighter manufacture can strand themselves below 50 free pop with no recovery path. Fix: `max(1, round(pop × POPULATION_GROWTH_RATE))` so there is always at least 1 growth per tick when population is below cap.

**~~*(2026-06-05)* Drained resources vanish — the attacker receives nothing from occupation.~~** *(Resolved — passive occupation drain was removed entirely. Resource extraction is now an explicit post-battle choice: Raid steals resources scaled to fleet firepower, Rout deals bonus damage to defenders. The "drain" mechanic no longer exists.)* The current drain implementation is pure denial; minerals and fuel intercepted from an occupied territory disappear. This makes economic raiding pointless and shapes the entire war motivation meta: without looting, conquest is only worthwhile if you hold territory permanently, which makes all wars existential and peace deals rare. CyberNations' raiding culture was driven by attacker receipt of stolen resources. **Decision needed before beta:** does the occupier receive the drained resources, or is denial the intended design?

**~~*(2026-06-05)* Fuel constraint makes rim empires structurally fuel-negative before fleet movement.** The N* ≈ 7 optimal territory count was derived from currency upkeep only. Fuel logistics cost at 10 territories is `LOGISTICS_FUEL_K × N(N+1)/2 = 1 × 55 = 55 fuel/tick`. A 10-territory rim empire with average development (one refinery each, richness ~1) produces ~50 fuel/tick at rest — already fuel-negative before any fleet moves. The actual joint-optimal territory count when both currency and fuel constraints are applied simultaneously may be 4–5. The N* values in the spec need a joint optimization pass before they are surfaced in the tutorial or documentation.~~ *(Not an issue, they simply need to devote more infrastructure to resource gain)*

**~~*(2026-06-05)* The shield mechanic creates a zero-damage threshold that enables free harassment.**~~ *(Fixed, but sending small harassment fleets could be used to increase dissent on key planets, may or may not be a problem)*

**~~*(2026-06-05)* Multi-war dissent piling is a potentially decisive counter-hegemon strategy.**~~ *(Fixed, dissent gains the maximum amount from any single war)*

**~~*(2026-06-06)* Holding fleet attrition is hardcoded at 2.5%/tick in `tick.py` but the spec's Decisions Log records it as 1%/tick.~~** *(Resolved — `HOLDING_ATTRITION_RATE = 0.025` added to `constants.py`; `tick.py` now uses the constant instead of a literal. Rate confirmed at 2.5%/tick; Decisions Log and What's Done updated to match.)* `tick.py` line 652 uses the literal `0.025`; `constants.py` does not define a `HOLDING_ATTRITION_RATE` constant. The Decisions Log entry reads "1% attrition with minimum 1 unit/tick." At 2.5%, a 100-unit fleet lasts ~40 ticks (80 hours) in contested holding — this is the figure the spec also quotes in the Decisions Log, suggesting the spec was updated to 1% without the code following. The net effect is that attrition is 2.5× harsher than documented and than veteran players will be told to expect. This is both a spec drift and a balance issue. Fix: define `HOLDING_ATTRITION_RATE = 0.01` in `constants.py`, import it in `tick.py`, and replace the literal. The rate itself should be monitored during beta but starting at the documented 1% rather than 2.5%.

***(2026-06-06)* The `post_battle_choice` window is 1 tick (2 hours), inconsistent with the 4-hour confirmation window and punishing for asynchronous play.** `tick.py` line 608–609 sets `fleet.confirmation_expires_at = tick_at + timedelta(hours=2)` after each combat round. A player whose fleet wins a combat round during tick N has until tick N+1 (2 hours) to choose Rout, Raid, or Raze. If they are offline during that window, the choice expires and combat resumes automatically — forcing a fight the player did not choose to start. The confirmation window for fleet arrival is 4 hours (2 ticks) because 2 hours is insufficient for an async player. The post-battle choice window applies the same "player must be online" pressure at every single combat round, every 2 hours, for the duration of a multi-tick war. A player fighting a 5-tick war who is offline for an 8-hour stretch will have 4 unexercised choices auto-expire. Set `post_battle_choice` window to 2 ticks (4 hours) to match the confirmation window standard. This requires changing `timedelta(hours=2)` to `timedelta(hours=4)` at line 609 and updating the spec's description of the mechanic.

**~~*(2026-06-06)* Raid can drain a nation to zero on all three resources in a single action with no minimum floor.~~** *(Resolved — raid cap is now production-based: each resource stolen is capped at `RAID_PRODUCTION_TICKS_CAP (= 3) × territory's per-tick production` for that resource. A territory with no active facilities produces nothing to raid. Tuning lever: `RAID_PRODUCTION_TICKS_CAP` in `constants.py`.)* `military.py` lines 691–704 compute stolen amounts as `min(random.uniform(0.5 × FP, 1.5 × FP), float(defender_nation.minerals))` independently for each resource. For a 100-unit fleet: FP = 200, so each resource steal is capped by the defender's stockpile with a max of 300 units stolen. There is no per-resource floor on what the defender retains. A nation with 500 minerals, 500 fuel, and 500 currency (reasonable at mid-game) can be raided to 200/200/200 or potentially 0/0/0 if the fleet is large enough. Against a small beta player with 1–2 territories, a single Raid from a large attacker can eliminate all stockpiled resources and leave them unable to queue any construction or manufacture for several ticks. CyberNations capped per-war raiding at 10% of the defender's resources per attack and had a 3-attack-per-day limit. P&W's loot system caps at 10% of the nation's gross bank balance. Some per-Raid cap — either a percentage of the defender's current stockpile (e.g., max 10%) or a cap based on the territory's production capacity — should be decided before beta. The current uncapped formula is observable and exploitable at the current 20–50 player scale.

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
| Shipyard | 150 min + 60 fuel + 2000¤ + 40 pop | 2 ticks (4h) | Without tutorial rewards: currency bottleneck (~40h). With tutorial rewards: queueable as soon as mine+refinery activate. |
| Fighter | 15 min + 30 fuel + 1000¤ + 1 pop | Instant (manufactured) | 2¤/tick currency upkeep + 1 fuel/tick if not docked on own territory |
| Probe | 1000 min + 500 fuel + 10000¤ | Instant (manufactured) | Very expensive — intended as a later-game action; stockpiling is required |
| Colony ship | 500 min + 1000 fuel | Instant (manufactured) | No currency cost; no pop cost at build; requires 100 unassigned pop to load |

**With tutorial rewards, the shipyard currency gate disappears.** Tutorial steps 1–4 award resources the moment actions are taken, well before any tick completes. The resource trace:

| Moment | Event | Min | Fuel | ¤ | Unassigned pop |
|---|---|---|---|---|---|
| Hour 0 | Start | 100 | 100 | 2000 | 100 |
| Hour 0 | Queue mine (Step 1: −60m −30f −500¤ / +500m +500¤) | 540 | 70 | 2000 | 90 |
| Hour 0 | Queue refinery (Step 2: −30m −60f −500¤ / +500f +500¤) | 510 | 510 | 2000 | 80 |
| Hour 0 | Visit planets (Step 3: +100m +100f +500¤) | 610 | 610 | 2500 | 80 |
| Hour 2 | Tick 1: mine+refinery active (+5m +5f +50¤ net) | 615 | 615 | **2550** | 80 |
| Hour 2 | Queue shipyard (Step 4: −150m −60f −2000¤ / +1000¤) | 465 | 555 | **1550** | 40 |
| Hour 4 | Tick 2: production (+5m +5f +50¤) | 470 | 560 | 1600 | 40 |
| Hour 6 | Tick 3: shipyard active (+5m +5f +50¤) | 475 | 565 | **1650** | 40 |
| Hour 6 | Manufacture fighter (Step 5: −15m −30f −1000¤ / +1000¤) | 460 | 535 | 1650 | 39 |

Production rates: mine = `max(5, round(richness × 2))` min/tick; refinery = same formula for fuel; currency income = 30¤/tick per active mine or refinery; territory upkeep = `10 × N²` = 10¤/tick at N=1; net currency = +50¤/tick with mine+refinery, +48¤/tick after adding 1 fighter.

The player has 2500¤ after the first few minutes of play — more than enough to queue the shipyard (2000¤) the moment mine+refinery activate at the 2-hour mark. The ~40-hour wait that existed without tutorial rewards is gone entirely.

~~**The colony ship population gate is now the dominant bottleneck.** After queuing mine (10 pop), refinery (10 pop), shipyard (40 pop), and fighter (1 pop), 61 population is assigned to infrastructure and 39 remains unassigned. Sending a colony ship requires 100 unassigned population loaded onto it. Population must grow first:~~ *(Updated to allow colony ships to load less than their maximum population capacity)*

**Probe is intentionally a late-game gate.** At 10000¤ cost and ~48¤/tick net income from a one-planet economy (with 1 fighter), a new player needs ~200 ticks (~400 hours) of income just for a single probe if they save every¤. This is wrong for a tutorial. Probes are not a new-player mechanic — the map already has terrain generated by seeding, so players can expand into pre-seeded territory using fleets (which claim unclaimed territory on arrival) without needing probes. The tutorial should deprioritize probes relative to the proposed flow. See recommendation below.

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

Reward: +1000 currency (half the shipyard cost) — awarded immediately when the build is queued.

**Step 5 — Manufacture a fighter** (triggers on: shipyard becomes active; completes on: fighter manufactured) **[implemented]**

Prompt: "Your shipyard is ready. Manufacture a fighter — your first military unit. Fighters have an ongoing currency upkeep cost of 2¤/tick and 1 fuel/tick when deployed away from home. A small standing garrison protects against opportunistic claims. Check the Military page to deploy it." Teach: upkeep exists and is ongoing; a single fighter stationed at home is cheap insurance; the Military page is where fleet management lives; fighters have stats (FP, Shields, SI) that matter in combat.

Reward: +1000 currency — awarded immediately when the fighter is manufactured.

**Step 6 — Review the event log** (triggers on: fighter manufactured; completes on: player visits /log) **[implemented]**

Prompt: "Open the Log page. Every tick generates entries: resource production, population changes, fleet status, and construction completions. This is your primary tool for understanding what happened while you were offline." Teach: the game is asynchronous; players should check the log after returning; teach what each entry type means.

Reward: none. UI orientation step.

**Step 7 — Understand the map and fleet dispatch** (triggers on: at least one fighter stationed; completes on: fleet dispatched to any node other than current location) **[implemented]**

Prompt: "From the Map, you can dispatch your fleet to any reachable node. Fleets travel at 2 nodes per tick. Dispatching to an unclaimed node claims it on arrival. Void nodes cannot be colonized or developed, but can be claimed to control trade routes. Dispatching to an enemy planet enters a 4-hour confirmation window before combat can occur." Teach: map fog-of-war basics; fleet pathfinding rules; the difference between planets and void nodes; the confirmation window and standing orders (hold/recall); that claiming is separate from colonizing.

Reward: +500 minerals, +500 fuel — awarded immediately on fleet dispatch.

**Step 8 — Build and send a colony ship** (triggers on: have at least 1 claimed territory with known richness, have 100+ unassigned pop, have a shipyard; completes on: colony ship manufactured) **[implemented]**

Prompt: "Claimed territory is owned but empty — no facilities can be built until population arrives. A colony ship loads up to 100 population from any colonized planet you own and carries it to a claimed planet. Build one at your shipyard. Colony ships travel 1 node per tick — slower than fighters." Teach: the two-step claim/colonize distinction; colony ship load/unload mechanics; slower speed than fighters; requires 100 unassigned pop at the source planet.

Reward: +500 minerals, +1000 fuel — awarded immediately when the colony ship is manufactured.

**Step 9 — Scout with a probe** (triggers on: colony ship manufactured; completes on: player clicks "Got it" in sidebar panel) **[implemented]**

Prompt: "When nearby space is claimed or too contested to expand into safely, probes let you scout further out. A probe reveals the resource richness of its destination — giving you intelligence before you commit a colony ship. Probe range is 10 nodes from your nearest colony. Data is destination-only (not along the path) and can be sold to other players. Build a probe at your shipyard when resources allow." Teach: probes are a tool for finding expansion opportunities beyond the contested frontier, not a prerequisite for all colonization; probe cost; range limitation; data is destination-only; the information economy exists; probe data is non-exclusive on sale.

Reward: none. Informational step; player acknowledges with "Got it" button in the tutorial sidebar.

**Step 10 — Tutorial complete** (triggers on: step 9 acknowledged; completes on: second planet colonized) **[implemented]**

Prompt: "You have a functioning multi-planet empire. The rest of the game is yours — expand, develop, trade, or pick a fight. Check the Diplomacy page to see who your neighbors are. Use the event log and the nation profiles page to track the competitive landscape." Point to remaining game systems without prescribing a path.

Reward: +1000 minerals, +1000 fuel, +2000 currency — awarded immediately on second territory colonization.

---

### What the Original Proposal Got Right and Wrong

**Good:** Mine before refinery before shipyard is the correct ordering. Both resources are needed before the shipyard can be queued. This sequence was kept as steps 1, 2, and 4.

**Fixed — fighter before colonization:** The original proposal put fighter creation before probing and colonization, implying combat was the next step after infrastructure. The implemented flow introduces the fighter at step 5 as "defense basics" alongside shipyard completion, without making it a gate on the colonization path.

**Fixed — probe before colony ship:** The original proposal had probing before the colony ship step. This was reversed: colony ship is step 8, probe is step 9. The seeded map gives new players nearby claimable territory without needing probes; probing is taught as the tool for pushing beyond the pre-seeded zone.

**Fixed — 90% population utilization gate:** The original proposal used 90% population utilization as the trigger for the probe/colonization steps. This gate is unachievable on a richness-1+1 home planet (pop starts at cap, never grows) and requires ~5 real days on higher-richness planets. Replaced with facility-completion gates throughout.

**Added — immediate rewards for steps 1 and 2:** Steps 1 (mine) and 2 (refinery) award resources the moment the player queues construction, not at tick completion. This provides immediate gratification during the first session rather than making new players wait 2 hours to see any feedback. Step 4 (shipyard) rewards at tick time — the wait is intentional there as part of the progression pacing.

**Added — step 3 as Planets page orientation:** The original proposal had no UI orientation step. Step 3 directs the player to the Planets tab and highlights the production section with an amber outline while the step is active. It auto-completes on page visit. This teaches currency income and upkeep at the moment those numbers first become visible.

**All 10 steps now implemented.** Steps 5–10 follow the same pattern as 1–4: action-triggered steps award rewards immediately in the relevant router endpoint; view/acknowledgement steps complete via dedicated API endpoints called by the frontend.

---

### Gating Logic Summary

| Tutorial step | Gate condition | Real-time estimate |
|---|---|---|
| Build mine (+500 min, +500¤) | Nation created | Day 1, first session |
| Build refinery (+500 fuel, +500¤) | Mine queued or active | Day 1, first session |
| Review planets (+100 min, +100 fuel, +500¤) | Mine or refinery active | Day 1, 2h in |
| Build shipyard (+1000¤) | Mine + refinery active | Day 1, ~2h in (tutorial rewards give 2500¤ before first tick; queue immediately when mine+refinery activate) |
| Manufacture fighter (+1000¤) | Shipyard active | Day 1, ~6h in (shipyard takes 2 ticks after queueing) |
| Read event log (no reward) | Fighter manufactured | Day 1, same session as fighter |
| Dispatch fleet (+500 min, +500 fuel) | Fighter stationed | Day 1–2 |
| Build colony ship (+500 min, +1000 fuel) | Claimed territory + 100 pop + shipyard | Day 3–5 |
| Scout with probe — Got it (no reward) | Colony ship manufactured | Day 3–5 |
| Colonize territory (+1000 min, +1000 fuel, +2000¤) | Step 9 acknowledged | Day 3–5 |

---

### Open Questions for Tutorial Design

- **Prompt format:** ~~Tooltip overlay, sidebar task list, or notification inbox?~~ **Resolved: sidebar task list.** Implemented as a persistent panel in the left nav sidebar, consistent with OGame's Advisor pattern. Overlays were rejected because they require the player to be online at the trigger moment.
- **Skip/dismiss:** ~~Can veteran players dismiss the tutorial?~~ **Resolved: yes.** A "Skip tutorial" button is present in the sidebar panel and sets `dismissed = true` immediately. No re-enable option in the current implementation; can be added if beta feedback requests it.
- **Starting currency:** With tutorial rewards, the player has 2500¤ after three quick first-session actions (mine, refinery, visit planets), which is enough to queue the shipyard as soon as mine+refinery activate. The ~40h currency wait that existed without rewards is gone. The 2000¤ starting balance is acceptable; do not raise it.
- **Home planet richness assignment:** The tutorial timing analysis assumes the home planet can have a pop cap above the starting 100 pop. If players pick a richness-1+1 planet (cap exactly 100), population never grows, and any growth-based tutorial gate fails. Either enforce a minimum home planet richness (e.g., mineral_richness + fuel_richness >= 4) at nation creation, or ensure no tutorial step uses population growth as a gate. The revised flow above avoids growth-based gates entirely, but the minimum richness question should be decided regardless for game balance reasons.
- **Probe tutorial timing:** Probes cost 10000¤ and 1000 min + 500 fuel. A single-planet economy running mine + refinery generates ~50¤/tick net and 5 min + 5 fuel/tick. Reaching probe cost from tutorial-complete state takes approximately 200 ticks for currency alone. This is by design (probes are a later-game tool), but the tutorial should set this expectation explicitly rather than implying probes are a near-term goal. The step 9 prompt as written does this.
- **Step 9 completion gate:** Should step 9 require the player to actually build and dispatch a probe to complete, or does the tutorial complete on colony ship manufacture (when the prompt appears)? Requiring a probe dispatch gives a stronger "done it once" confirmation but the cost (~200 ticks of savings) means most new players will not complete step 9 quickly. Consider whether an incomplete tutorial is worse than a tutorial that takes weeks to finish.


### Defense combat decisions

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