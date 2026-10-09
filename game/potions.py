"""Potions: used in duels only, one per turn, the effect is for that turn.

Potions are stackable items (items table): ("potion", "<kind>"). They are
found in drops and on bosses, and can be traded like any item.
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


def _cfg() -> dict:
    return settings.get()["potions"]


def max_per_duel() -> int:
    return int(_cfg()["max_per_duel"])


def label(key: str) -> str:
    return f"Potion of {POTIONS[key].name}"


def effect_text(key: str) -> str:
    c = _cfg()
    if key == "strength":
        return f"this turn's attack +{float(c['strength_bonus']):.0%}"
    if key == "speed":
        return f"{float(c['speed_chance']):.0%} chance to strike twice, this turn and the next {int(c['speed_turns']) - 1}"
    if key == "healing":
        return f"heal {float(c['healing_hp']):g} HP"
    return f"{float(c['harming_damage']):g} direct damage to the opponent (ignores armor)"


def check(key: str) -> str:
    if key not in POTIONS:
        raise GameError("Unknown potion. Pick one from the suggestions.")
    return key


def owned(ctx: Ctx, user_id: int) -> dict[str, int]:
    """kind -> amount, for the potions the player has."""
    return {
        material: amount
        for (item, material), amount in players.get_items(ctx, user_id).items()
        if item == "potion" and material in POTIONS
    }


def give(ctx: Ctx, user_id: int, key: str, amount: int = 1) -> None:
    players.add_item(ctx, user_id, "potion", check(key), amount)


def give_random(ctx: Ctx, user_id: int, amount: int = 1) -> list[str]:
    found = [ctx.rng.choice(sorted(POTIONS)) for _ in range(amount)]
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
