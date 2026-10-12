from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import dummy, settings
from game.errors import GameError
from utils.checks import check_game_channel
from utils.ui import join_lines

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
GEAR_CHOICES = [app_commands.Choice(name=f"{name} dummy", value=key) for key, name in dummy.GEARS.items()]


class DummyCog(commands.Cog):
    """/dummy: a damage tester with a leaderboard, and training duels."""

    group = app_commands.Group(name="dummy", description="Training dummy: test your damage, or train for duels.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @group.command(name="hit", description="Hit the training dummy: your damage with your current gear.")
    async def hit(self, interaction: discord.Interaction):
        check_game_channel(interaction)
        res = await self.bot.db.run(dummy.hit_series, interaction.user.id)
        hits = " · ".join(f"💥 **{h:g}**" if crit else f"{h:g}" for h, crit in res["hits"])
        low, high = res["attack"]
        embed = discord.Embed(
            title=f"🎯 {interaction.user.display_name} hits the training dummy",
            description=f"{hits}\n\n**Total: {res['total']:g}** damage in {len(res['hits'])} hits",
            color=discord.Color.green() if res["record"] else discord.Color.blurple(),
        )
        embed.add_field(name="Average", value=f"{res['average']:g}", inline=True)
        embed.add_field(name="Min – max", value=f"{res['min']:g} – {res['max']:g}", inline=True)
        embed.add_field(name="Critical hits", value=str(res["crits"]), inline=True)
        best = f"Best series **{res['best_total']:g}** · best hit **{res['best_hit']:g}**"
        if res["rank"]:
            best += f" · #{res['rank']} of {res['players']} (`/dummy top`)"
        embed.add_field(name="🏅 New personal best!" if res["record"] else "Your records", value=best, inline=False)
        embed.set_footer(text=f"Your gear: {low:g}–{high:g} per hit (x{settings.get()['duel']['crit_multiplier']:g} on a "
                              "critical hit). The dummy has no armor; nothing wears out.")
        await interaction.response.send_message(embed=embed)

    @group.command(name="top", description="The best series on the training dummy.")
    async def top(self, interaction: discord.Interaction):
        rows = await self.bot.db.run(dummy.ranking)
        lines = [
            f"{MEDALS.get(i, f'`#{i}`')} <@{r['user_id']}> — **{r['best_total']:g}** (best hit {r['best_hit']:g})"
            for i, r in enumerate(rows[:10], start=1)
        ]
        embed = discord.Embed(
            title="🎯 Training dummy — best series",
            description=join_lines(lines, 4000, "Nobody has hit the dummy yet: `/dummy hit`!"),
            color=discord.Color.gold(),
        )
        mine = next((i for i, r in enumerate(rows, start=1) if r["user_id"] == interaction.user.id), None)
        if mine:
            r = rows[mine - 1]
            embed.add_field(name="You", value=f"#{mine} — **{r['best_total']:g}** (best hit {r['best_hit']:g})")
        embed.set_footer(text=f"A series = {settings.get()['dummy']['hits']} hits with your gear and species.")
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="duel", description="Train: a duel against a dummy that hits back. Nothing used up, nothing won.")
    @app_commands.describe(gear="How the dummy is equipped (sword and armor)")
    @app_commands.choices(gear=GEAR_CHOICES)
    async def duel(self, interaction: discord.Interaction, gear: str = "iron"):
        duels = self.bot.get_cog("DuelCog")
        if duels is None:
            raise GameError("Duels aren't available right now.")
        await duels.start_training(interaction, gear)  # type: ignore[attr-defined]


async def setup(bot: commands.Bot):
    await bot.add_cog(DummyCog(bot))
