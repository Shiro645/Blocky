from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.config import load_emojis

EMOJI = load_emojis()

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

class EconomyCraftListCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="craftlist", description="Show all crafting recipes.")
    async def craftlist(self, interaction: discord.Interaction):
        lines = []
        for item, (ingots, sticks) in RECIPES.items():
            cost = []
            if ingots:
                cost.append(f"{ingots} ingot(s)")
            if sticks:
                cost.append(f"{EMOJI['stick']} {sticks} stick(s)")
            lines.append(f"**{item}** → " + " + ".join(cost))

        embed = discord.Embed(title="Crafting Recipes", description="\n".join(lines))
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCraftListCog(bot))
