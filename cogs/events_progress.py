from __future__ import annotations

from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from game import biomes, progress, seasons
from utils.ui import em, join_lines, progress_bar


class ProgressCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="challenges", description="Show today's and this week's challenges and your progress.")
    async def challenges(self, interaction: discord.Interaction):
        def load(ctx, user_id):
            day_ends = int(datetime.combine(ctx.today + timedelta(days=1), datetime.min.time(),
                                            tzinfo=ctx.local_now.tzinfo).timestamp())
            return (progress.daily_challenges(ctx, user_id), day_ends,
                    progress.weekly_challenges(ctx, user_id), seasons.season_end(ctx),
                    biomes.current(ctx), progress.biome_progress(ctx, user_id))

        day, day_ends, week, week_ends, biome, biome_challenge = await self.bot.db.run(load, interaction.user.id)

        def lines(entries: list[dict]) -> str:
            out = []
            for c in entries:
                mark = "✅" if c["completed"] else "🎯"
                out.append(
                    f"{mark} **{c['text']}** — reward {em(c['reward'])}\n"
                    f"`{progress_bar(c['progress'], c['target'], 12)}` {c['progress']:,}/{c['target']:,}"
                )
            return "\n\n".join(out)

        embed = discord.Embed(title="🎯 Challenges", color=discord.Color.purple())
        if day:
            embed.add_field(name="📅 Today", value=f"{lines(day)}\n\nNew ones <t:{day_ends}:R>.", inline=False)
        if week:
            embed.add_field(name="🗓️ This week", value=f"{lines(week)}\n\nNew ones <t:{week_ends}:R>.", inline=False)
        if biome_challenge:
            embed.add_field(name=f"{biome.label}: the biome's challenge", value=f"{lines([biome_challenge])}\n\n"
                            "Paid apart (not counted for the weekly book). `/biome`", inline=False)
        if not day and not week:
            embed.description = "No challenges right now."
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
        room = [5500]  # an embed holds 6,000 characters in all

        def add(name: str, lines: list[str], empty: str) -> None:
            """As many fields as needed (1,024 characters each), while the embed has room."""
            if not lines:
                embed.add_field(name=name, value=empty, inline=False)
                return
            chunks, chunk, size = [], [], 0
            for line in lines:
                if chunk and size + len(line) + 1 > 1024:
                    chunks.append(chunk)
                    chunk, size = [], 0
                chunk.append(line)
                size += len(line) + 1
            chunks.append(chunk)
            for i, chunk in enumerate(chunks):
                value = "\n".join(chunk)
                if len(value) > room[0] or len(embed.fields) >= 24:
                    embed.add_field(name="\u200b", value=f"…and {sum(len(c) for c in chunks[i:])} more", inline=False)
                    return
                embed.add_field(name=name if i == 0 else "\u200b", value=value, inline=False)
                room[0] -= len(value)

        add("Unlocked", unlocked, "None yet.")
        if target.id == interaction.user.id:
            add("Still to unlock", locked, "All done! 🎉")
        await interaction.response.send_message(embed=embed, ephemeral=target.id == interaction.user.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProgressCog(bot))
