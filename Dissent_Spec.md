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
