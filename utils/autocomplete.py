from __future__ import annotations

from discord import app_commands

from game import assets


async def owned_asset_choices(bot, user_id: int, current: str, *, emeralds: bool = True) -> list[app_commands.Choice[str]]:
    """Autocomplete entries for what `user_id` owns, e.g. 'iron ingot (12)'."""
    owned = await bot.db.run(assets.owned, user_id)
    current = current.lower()
    choices = []
    for key, amount in owned:
        if key == "emeralds" and not emeralds:
            continue
        name = f"{assets.describe(key)} ({amount})"
        if current in name.lower():
            choices.append(app_commands.Choice(name=name, value=key))
    return choices[:25]
