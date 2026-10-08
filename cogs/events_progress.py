from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import progress, seasons
from utils.ui import em, join_lines, progress_bar


class ProgressCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="challenges", description="Show this week's challenges and your progress.")
    async def challenges(self, interaction: discord.Interaction):
        def load(ctx, user_id):
            return progress.weekly_challenges(ctx, user_id), seasons.season_end(ctx)

        week, ends_at = await self.bot.db.run(load, interaction.user.id)
        lines = []
        for c in week:
            mark = "✅" if c["completed"] else "🎯"
            lines.append(
                f"{mark} **{c['text']}** — reward {em(c['reward'])}\n"
                f"`{progress_bar(c['progress'], c['target'], 12)}` {c['progress']:,}/{c['target']:,}"
            )
        embed = discord.Embed(
            title="🎯 Weekly challenges",
            description="\n\n".join(lines) + f"\n\nNew challenges <t:{ends_at}:R>.",
            color=discord.Color.purple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="achievements", description="Show unlocked and remaining achievements.")
    @app_commands.describe(member="Player to look at (yourself by default)")
    async def achievements(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        data = await self.bot.db.run(progress.achievements_overview, target.id)
        unlocked = [f"{a.icon} **{a.name}** — {a.description} (<t:{ts}:d>)" for a, ts in data["unlocked"]]
        locked = [f"🔒 **{a.name}** — {a.description} · {em(a.reward)}" for a in data["locked"]]
        total = len(unlocked) + len(locked)

        embed = discord.Embed(
            title=f"🏅 {target.display_name}'s achievements ({len(unlocked)}/{total})",
            color=discord.Color.purple(),
        )
        embed.add_field(name="Unlocked", value=join_lines(unlocked, empty="None yet."), inline=False)
        if target.id == interaction.user.id:
            embed.add_field(name="Still to unlock", value=join_lines(locked, empty="All done! 🎉"), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=target.id == interaction.user.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProgressCog(bot))
