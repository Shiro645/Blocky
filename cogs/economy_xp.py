from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import players, settings
from game.catalog import TALENT_BRANCHES, TALENT_INFO
from utils.ui import EMOJI, progress_bar

BRANCH_CHOICES = [app_commands.Choice(name=b, value=b) for b in TALENT_BRANCHES]


class EconomyXPCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="xp", description="Show your XP, level and talent points.")
    async def xp(self, interaction: discord.Interaction):
        p = await self.bot.db.run(players.get_user, interaction.user.id)
        req = players.xp_required_for_level(p["level"])

        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Progress",
            description=(
                f"Level **{p['level']}**\n"
                f"{EMOJI['xp']} XP: **{p['xp']} / {req}**\n"
                f"`{progress_bar(p['xp'], req)}`"
            ),
            color=discord.Color.teal(),
        )
        embed.add_field(name="Talent points", value=str(p["talent_points"]), inline=True)
        for b in TALENT_BRANCHES:
            embed.add_field(
                name=b.capitalize(), value=f"{p[b + '_points']} / {players.talent_cap(b)}", inline=True
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="talents", description="Show talent branches and how they work.")
    async def talents(self, interaction: discord.Interaction):
        p = await self.bot.db.run(players.get_user, interaction.user.id)
        lines = [
            f"**{b}** ({p[b + '_points']}/{players.talent_cap(b)}): {TALENT_INFO[b]}"
            for b in TALENT_BRANCHES
        ]
        embed = discord.Embed(
            title="Talents",
            description="Spend your talent points to specialize your progression.\n\n" + "\n".join(lines),
            color=discord.Color.teal(),
        )
        embed.add_field(name="Your talent points", value=str(p["talent_points"]), inline=False)
        embed.add_field(
            name="How to earn and spend",
            value=(
                f"You earn 1 point every **{settings.get()['talents']['points_every_levels']}** levels. "
                "Spend them with `/talent_buy`."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="talent_buy", description="Spend talent points into a branch.")
    @app_commands.choices(branch=BRANCH_CHOICES)
    async def talent_buy(
        self, interaction: discord.Interaction, branch: str, points: app_commands.Range[int, 1, 100] = 1
    ):
        updated = await self.bot.db.run(players.buy_talent, interaction.user.id, branch, points)
        await interaction.response.send_message(
            f"✅ Spent **{points}** point(s) into **{branch}**. "
            f"Now: **{updated[branch + '_points']}/{players.talent_cap(branch)}**.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyXPCog(bot))
