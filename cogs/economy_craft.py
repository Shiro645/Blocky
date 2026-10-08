from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from database import init_db, ensure_user, add_gear, get_item_amount, remove_item_checked

from utils.config import load_emojis

EMOJI = load_emojis()

MATERIALS = ("gold", "iron", "diamond", "netherite")

RECIPES = {
    "sword": (2, 1),
    "pickaxe": (3, 2),
    "axe": (3, 2),
    "shovel": (1, 2),
    "hoe": (2, 2),
    "helmet": (5, 0),
    "chestplate": (8, 0),
    "leggings": (7, 0),
    "boots": (4, 0),
}

def mat_emoji(material: str) -> str:
    return EMOJI.get(material, "")

class EconomyCraftCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()

    @app_commands.command(name="craft", description="Craft tools and armor using ingots and sticks.")
    async def craft(self, interaction: discord.Interaction, item: str, material: str):
        item = item.lower().strip()
        material = material.lower().strip()

        if item not in RECIPES:
            return await interaction.response.send_message(
                f"❌ Invalid item. Allowed: {', '.join(RECIPES.keys())}",
                ephemeral=True,
            )

        if material not in MATERIALS:
            return await interaction.response.send_message(
                f"❌ Invalid material. Allowed: {', '.join(MATERIALS)}",
                ephemeral=True,
            )

        ensure_user(interaction.user.id)

        ingots_needed, sticks_needed = RECIPES[item]
        ingots_have = get_item_amount(interaction.user.id, "ingot", material)
        sticks_have = get_item_amount(interaction.user.id, "stick", "none")

        missing = []
        if ingots_have < ingots_needed:
            missing.append(f"{mat_emoji(material)} **{ingots_needed - ingots_have} {material} ingot(s)**")
        if sticks_have < sticks_needed:
            missing.append(f"{EMOJI['stick']} **{sticks_needed - sticks_have} stick(s)**")

        if missing:
            return await interaction.response.send_message(
                "❌ Not enough resources. Missing:\n" + "\n".join(f"- {m}" for m in missing),
                ephemeral=True,
            )

        if not remove_item_checked(interaction.user.id, "ingot", material, ingots_needed):
            return await interaction.response.send_message("❌ Inventory changed. Try again.", ephemeral=True)
        if not remove_item_checked(interaction.user.id, "stick", "none", sticks_needed):
            return await interaction.response.send_message("❌ Inventory changed. Try again.", ephemeral=True)

        add_gear(interaction.user.id, item, material)

        cost_parts = []
        if ingots_needed:
            cost_parts.append(f"{mat_emoji(material)} {ingots_needed} ingot(s)")
        if sticks_needed:
            cost_parts.append(f"{EMOJI['stick']} {sticks_needed} stick(s)")

        await interaction.response.send_message(
            f"✅ Crafted {mat_emoji(material)} **{material} {item}**!\nCost: " + " + ".join(cost_parts),
            ephemeral=True,
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCraftCog(bot))
