from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import shop
from game.catalog import GEAR_ITEMS, MATERIALS, RECIPES
from utils.ui import EMOJI, mat

ITEM_CHOICES = [app_commands.Choice(name=i, value=i) for i in GEAR_ITEMS]
MATERIAL_CHOICES = [app_commands.Choice(name=m, value=m) for m in MATERIALS]


class EconomyCraftCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="craft", description="Craft tools and armor using ingots and sticks.")
    @app_commands.choices(item=ITEM_CHOICES, material=MATERIAL_CHOICES)
    async def craft(self, interaction: discord.Interaction, item: str, material: str):
        res = await self.bot.db.run(shop.craft, interaction.user.id, item, material)

        cost = []
        if res["ingots"]:
            cost.append(f"{mat(material)} {res['ingots']} ingot(s)".strip())
        if res["sticks"]:
            cost.append(f"{EMOJI['stick']} {res['sticks']} stick(s)".strip())
        await interaction.response.send_message(
            f"✅ Crafted {mat(material)} **{material} {item}**! Cost: " + " + ".join(cost),
            ephemeral=True,
        )

    @app_commands.command(name="craftlist", description="Show all crafting recipes.")
    async def craftlist(self, interaction: discord.Interaction):
        lines = []
        for item, (ingots, sticks) in RECIPES.items():
            cost = []
            if ingots:
                cost.append(f"{ingots} ingot(s)")
            if sticks:
                cost.append(f"{EMOJI['stick']} {sticks} stick(s)".strip())
            lines.append(f"**{item}** → " + " + ".join(cost))

        embed = discord.Embed(title="Crafting Recipes", description="\n".join(lines))
        embed.set_footer(text="Materials: " + ", ".join(MATERIALS))
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCraftCog(bot))
