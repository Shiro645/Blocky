"""Potions: used in duels only, one per turn, the effect is for that turn.

Potions are stackable items (items table): ("potion", "<kind>") for level I
and ("potion", "<kind>:2") for the reinforced level II, sold only by the
villager. They are found in drops and on bosses, and can be traded like any item.
"""
from __future__ import annotations

from dataclasses import dataclass

from game import players, settings
from game.db import Ctx
from game.errors import GameError


@dataclass(frozen=True)
class Potion:
    key: str
    name: str
    icon: str  # fallback when the emoji isn't uploaded


POTIONS: dict[str, Potion] = {
    p.key: p
    for p in (
        Potion("strength", "Strength", "💪"),
        Potion("speed", "Speed", "⚡"),
        Potion("healing", "Healing", "❤️"),
        Potion("harming", "Harming", "☠️"),
    )
}


MAX_LEVEL = 2


def _cfg() -> dict:
    return settings.get()["potions"]


def max_per_duel() -> int:
    return int(_cfg()["max_per_duel"])


# ---------------- keys ----------------
def parse(key: str) -> tuple[str, int]:
    """'strength' -> ('strength', 1), 'strength:2' -> ('strength', 2)"""
    kind, _, level = key.partition(":")
    if kind not in POTIONS or (level and level not in {str(n) for n in range(2, MAX_LEVEL + 1)}):
        raise GameError("Unknown potion. Pick one from the suggestions.")
    return kind, int(level or 1)


def key_of(kind: str, level: int = 1) -> str:
    return kind if level <= 1 else f"{kind}:{level}"


def check(key: str) -> str:
    parse(key)
    return key


def name(key: str) -> str:
    """'Strength', 'Strength II'"""
    kind, level = parse(key)
    return POTIONS[kind].name + (" II" if level == 2 else "")


def label(key: str) -> str:
    return f"Potion of {name(key)}"


# ---------------- effects ----------------
def effect(key: str, setting: str) -> float:
    """A potion's effect: the settings value, multiplied for level II."""
    _, level = parse(key)
    value = float(_cfg()[setting])
    return value * float(_cfg()["level2_multiplier"]) if level >= 2 else value


def effect_text(key: str) -> str:
    kind, _ = parse(key)
    if kind == "strength":
        return f"this turn's attack: minimum damage +{effect(key, 'strength_min_bonus'):g}"
    if kind == "speed":
        chance = min(1.0, effect(key, "speed_chance"))
        return f"{chance:.0%} chance to strike twice, this turn and the next {int(_cfg()['speed_turns']) - 1}"
    if kind == "healing":
        return f"heal {effect(key, 'healing_hp'):g} HP"
    return f"{effect(key, 'harming_damage'):g} direct damage to the opponent (reduced by armor)"


def value(key: str) -> float:
    """Reference value in emeralds."""
    _, level = parse(key)
    return float(_cfg()["value_ii"] if level >= 2 else _cfg()["value"])


def owned(ctx: Ctx, user_id: int) -> dict[str, int]:
    """potion key -> amount, for the potions the player has."""
    return {
        material: amount
        for (item, material), amount in players.get_items(ctx, user_id).items()
        if item == "potion" and material.partition(":")[0] in POTIONS
    }


def give(ctx: Ctx, user_id: int, key: str, amount: int = 1) -> None:
    players.add_item(ctx, user_id, "potion", check(key), amount)


def give_random(ctx: Ctx, user_id: int, amount: int = 1, level: int = 1) -> list[str]:
    found = [key_of(ctx.rng.choice(sorted(POTIONS)), level) for _ in range(amount)]
    for key in found:
        give(ctx, user_id, key)
    return found


def drink(ctx: Ctx, user_id: int, key: str) -> None:
    """Use one potion from the inventory."""
    check(key)
    if players.item_amount(ctx, user_id, "potion", key) < 1:
        raise GameError(f"You don't have a **{label(key)}** anymore.")
    players.take_item(ctx, user_id, "potion", key, 1)
    players.bump_stat(ctx, user_id, "potions_drunk")
