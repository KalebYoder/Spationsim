"""
Tests for fleet combat tick resolution.

Damage model:
  raw_damage      = firing_count × firepower
  shield_absorbed = target_count × shields
  net_damage      = max(0, raw_damage − shield_absorbed)
  losses          = max(1, round(net_damage / structural_integrity))
                    if net_damage > 0 else 0

Both sides fire simultaneously.
"""
from app.services.combat import resolve_combat_tick

# Canonical unit matching UNIT_STATS["starfighter"]
SF = {"firepower": 2, "shields": 1, "structural_integrity": 5}

# Heavier unit for cross-type tests
HC = {"firepower": 8, "shields": 4, "structural_integrity": 20}


# ---------------------------------------------------------------------------
# Zero / empty fleet guards
# ---------------------------------------------------------------------------

def test_zero_attackers_returns_no_losses():
    assert resolve_combat_tick(0, SF, 100, SF) == (0, 0)


def test_zero_defenders_returns_no_losses():
    assert resolve_combat_tick(100, SF, 0, SF) == (0, 0)


def test_both_zero_returns_no_losses():
    assert resolve_combat_tick(0, SF, 0, SF) == (0, 0)


# ---------------------------------------------------------------------------
# Shield absorption — defender side
# ---------------------------------------------------------------------------

def test_shields_fully_block_when_raw_damage_equals_shield_total():
    # 50 × 2 = 100 raw; 100 × 1 = 100 absorbed → net 0 → 0 defender losses
    _, defender_losses = resolve_combat_tick(50, SF, 100, SF)
    assert defender_losses == 0


def test_shields_fully_block_when_raw_damage_below_shield_total():
    # 10 × 2 = 20 raw; 100 × 1 = 100 absorbed → net 0 → 0 defender losses
    _, defender_losses = resolve_combat_tick(10, SF, 100, SF)
    assert defender_losses == 0


def test_one_unit_above_threshold_causes_minimum_one_loss():
    # 51 × 2 = 102 raw; 100 × 1 = 100 absorbed; net 2
    # round(2 / 5) = 0 → max(1, 0) = 1
    _, defender_losses = resolve_combat_tick(51, SF, 100, SF)
    assert defender_losses == 1


def test_attacker_fully_blocked_by_overwhelming_defenders():
    # 5 × 2 = 10 raw; 1000 × 1 = 1000 absorbed → net 0 → 0 defender losses
    _, defender_losses = resolve_combat_tick(5, SF, 1000, SF)
    assert defender_losses == 0


# ---------------------------------------------------------------------------
# Shield absorption — attacker side
# ---------------------------------------------------------------------------

def test_attacker_still_takes_losses_when_defenders_block_all_incoming():
    # Defender fire: 100 × 2 = 200 raw; 10 × 1 = 10 absorbed → 190 net → losses > 0
    attacker_losses, _ = resolve_combat_tick(10, SF, 100, SF)
    assert attacker_losses > 0


def test_attacker_shields_fully_block_defender_fire():
    # 200 attackers vs 100 defenders
    # Defender fire: 100 × 2 = 200 raw; 200 × 1 = 200 absorbed → net 0
    attacker_losses, _ = resolve_combat_tick(200, SF, 100, SF)
    assert attacker_losses == 0


# ---------------------------------------------------------------------------
# Equal forces — symmetry
# ---------------------------------------------------------------------------

def test_equal_forces_produce_equal_losses():
    a_losses, d_losses = resolve_combat_tick(100, SF, 100, SF)
    assert a_losses == d_losses


def test_equal_forces_100_each_exact_values():
    # 100 × 2 = 200 raw; 100 × 1 = 100 absorbed; net 100; round(100 / 5) = 20
    a_losses, d_losses = resolve_combat_tick(100, SF, 100, SF)
    assert a_losses == 20
    assert d_losses == 20


def test_equal_forces_50_each_exact_values():
    # 50 × 2 = 100 raw; 50 × 1 = 50 absorbed; net 50; round(50 / 5) = 10
    a_losses, d_losses = resolve_combat_tick(50, SF, 50, SF)
    assert a_losses == 10
    assert d_losses == 10


def test_equal_forces_1_each():
    # 1 × 2 = 2 raw; 1 × 1 = 1 absorbed; net 1; max(1, round(1/5)) = 1
    a_losses, d_losses = resolve_combat_tick(1, SF, 1, SF)
    assert a_losses == 1
    assert d_losses == 1


# ---------------------------------------------------------------------------
# Asymmetric forces
# ---------------------------------------------------------------------------

def test_larger_attacker_causes_more_defender_losses():
    _, d_losses_large = resolve_combat_tick(200, SF, 100, SF)
    _, d_losses_small = resolve_combat_tick(100, SF, 100, SF)
    assert d_losses_large > d_losses_small


def test_attacker_2x_force_exact_values():
    # Attacker damage: 200 × 2 = 400; 100 × 1 = 100 absorbed; 300 net; round(300/5) = 60
    # Defender damage: 100 × 2 = 200; 200 × 1 = 200 absorbed; net 0 → 0 attacker losses
    a_losses, d_losses = resolve_combat_tick(200, SF, 100, SF)
    assert a_losses == 0
    assert d_losses == 60


def test_small_attacker_vs_large_defender_exact_values():
    # 10 attackers vs 100 defenders
    # Attacker damage: 10 × 2 = 20; 100 × 1 = 100 absorbed → 0 defender losses
    # Defender damage: 100 × 2 = 200; 10 × 1 = 10 absorbed; 190 net; round(190/5) = 38
    a_losses, d_losses = resolve_combat_tick(10, SF, 100, SF)
    assert d_losses == 0
    assert a_losses == 38


def test_overwhelming_attacker_exact_values():
    # 1000 vs 10
    # To defender: 1000 × 2 = 2000; 10 × 1 = 10; net 1990; round(1990/5) = 398
    # To attacker: 10 × 2 = 20; 1000 × 1 = 1000; net 0 → 0
    a_losses, d_losses = resolve_combat_tick(1000, SF, 10, SF)
    assert a_losses == 0
    assert d_losses == 398


# ---------------------------------------------------------------------------
# Minimum-one-loss rule
# ---------------------------------------------------------------------------

def test_minimum_one_loss_when_net_damage_rounds_to_zero():
    # net 2 / SI 5 = 0.4 → round = 0 → max(1, 0) = 1
    _, defender_losses = resolve_combat_tick(51, SF, 100, SF)
    assert defender_losses == 1


def test_no_losses_when_net_damage_is_exactly_zero():
    _, defender_losses = resolve_combat_tick(50, SF, 100, SF)
    assert defender_losses == 0


# ---------------------------------------------------------------------------
# Custom / alternate unit stats
# ---------------------------------------------------------------------------

def test_heavy_cruiser_vs_heavy_cruiser_equal_forces():
    # 100 × 8 = 800 raw; 100 × 4 = 400 absorbed; 400 net; round(400/20) = 20
    a_losses, d_losses = resolve_combat_tick(100, HC, 100, HC)
    assert a_losses == 20
    assert d_losses == 20


def test_zero_shields_all_damage_reaches_hull():
    no_shield = {"firepower": 2, "shields": 0, "structural_integrity": 5}
    # 100 × 2 = 200 raw; 0 absorbed; 200 net; round(200/5) = 40
    a_losses, d_losses = resolve_combat_tick(100, no_shield, 100, no_shield)
    assert a_losses == 40
    assert d_losses == 40


def test_fighters_cannot_pierce_cruiser_shields():
    # 100 SF vs 100 HC
    # To HC: 100 × 2 = 200 raw; 100 × 4 = 400 absorbed → net 0 → 0 HC losses
    # To SF: 100 × 8 = 800 raw; 100 × 1 = 100 absorbed; 700 net; round(700/5) = 140
    a_losses, d_losses = resolve_combat_tick(100, SF, 100, HC)
    assert d_losses == 0
    assert a_losses == 140


def test_cruisers_vs_fighters_exact_values():
    # 100 HC vs 100 SF (attacker = HC, defender = SF)
    # To SF: 100 × 8 = 800 raw; 100 × 1 = 100 absorbed; 700 net; round(700/5) = 140
    # To HC: 100 × 2 = 200 raw; 100 × 4 = 400 absorbed → net 0 → 0 HC losses
    a_losses, d_losses = resolve_combat_tick(100, HC, 100, SF)
    assert a_losses == 0
    assert d_losses == 140


def test_high_structural_integrity_reduces_losses():
    tanky = {"firepower": 2, "shields": 0, "structural_integrity": 20}
    fragile = {"firepower": 2, "shields": 0, "structural_integrity": 5}
    _, d_losses_tanky = resolve_combat_tick(100, fragile, 100, tanky)
    _, d_losses_fragile = resolve_combat_tick(100, fragile, 100, fragile)
    assert d_losses_tanky < d_losses_fragile


def test_high_attack_increases_losses():
    strong = {"firepower": 10, "shields": 1, "structural_integrity": 5}
    _, d_losses_strong = resolve_combat_tick(100, strong, 100, SF)
    _, d_losses_normal = resolve_combat_tick(100, SF, 100, SF)
    assert d_losses_strong > d_losses_normal


# ---------------------------------------------------------------------------
# Return type guarantees
# ---------------------------------------------------------------------------

def test_return_value_is_tuple_of_two_ints():
    result = resolve_combat_tick(100, SF, 100, SF)
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert all(isinstance(v, int) for v in result)


def test_losses_are_non_negative():
    a_losses, d_losses = resolve_combat_tick(100, SF, 100, SF)
    assert a_losses >= 0
    assert d_losses >= 0


def test_zero_input_returns_ints_not_none():
    result = resolve_combat_tick(0, SF, 100, SF)
    assert result == (0, 0)
    assert all(isinstance(v, int) for v in result)
