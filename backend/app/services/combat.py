from __future__ import annotations


def resolve_combat_tick(
    attacker_count: int,
    attacker_stats: dict,
    defender_count: int,
    defender_stats: dict,
    home_territory_multiplier: float = 1.0,
) -> tuple[int, int]:
    """
    Resolve one tick of fleet combat.  Returns (attacker_losses, defender_losses).

    Damage model per side each tick:
      raw_damage      = firing_count × firepower
      shield_absorbed = target_count × shields
      net_damage      = max(0, raw_damage − shield_absorbed)
      losses          = max(1, round(net_damage / structural_integrity))
                        if net_damage > 0 else 0

    Both sides fire simultaneously; losses are calculated before being applied.

    home_territory_multiplier: when > 1.0 (defender fighting on their own colonized
    territory), the defender's effective count is inflated for the purpose of absorbing
    the attacker's fire only. Defender return fire always targets the real attacker count.
    """
    if attacker_count <= 0 or defender_count <= 0:
        return 0, 0

    def _losses(
        firing_count: int,
        firing_stats: dict,
        target_count: int,
        target_stats: dict,
    ) -> int:
        raw = firing_count * firing_stats["firepower"]
        absorbed = target_count * target_stats["shields"]
        net = max(0, raw - absorbed)
        if net == 0:
            return 0
        return max(1, round(net / target_stats["structural_integrity"]))

    defender_effective = round(defender_count * home_territory_multiplier)
    attacker_losses = _losses(defender_count, defender_stats, attacker_count, attacker_stats)
    defender_losses = _losses(attacker_count, attacker_stats, defender_effective, defender_stats)
    return attacker_losses, defender_losses
