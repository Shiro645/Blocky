from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import seasons, teams
from utils.config import role_id
from utils.ui import em, tag_prefix

log = logging.getLogger("seasons")

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def medal(rank: int) -> str:
    return MEDALS.get(rank, f"`#{rank}`")


class SeasonsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.close_loop.start()

    async def cog_unload(self) -> None:
        self.close_loop.cancel()

    @tasks.loop(minutes=5)
    async def close_loop(self):
        try:
            await self.close_tick()
        except Exception:  # an error must never stop the loop
            log.exception("Season loop failed")

    async def close_tick(self) -> None:
        # Seasons are closed (and paid) in the database first: each announcement
        # is isolated, so one that fails can't stop the champion role or the others.
        closed = await self.bot.db.run(seasons.close_finished)
        if closed:
            champion = closed[-1]["podium"][0]["user_id"] if closed[-1]["podium"] else None
            await self.safely(self.move_champion_role(champion), "move the champion role")
        for season in closed:
            await self.safely(self.announce(season), f"announce season {season['season_id']}")
        for season in await self.bot.db.run(teams.close_finished):
            await self.safely(self.announce_teams(season), f"announce team season {season['season_id']}")

    @staticmethod
    async def safely(coro, what: str) -> None:
        try:
            await coro
        except Exception:
            log.exception("Could not %s", what)

    @close_loop.before_loop
    async def before_close_loop(self):
        await self.bot.wait_until_ready()

    async def announce(self, season: dict) -> None:
        podium = season["podium"]
        if not podium:
            return
        lines = [
            f"{medal(p['rank'])} <@{p['user_id']}> — {em(p['score'])} earned · reward **+{em(p['reward'])}**"
            for p in podium
        ]
        embed = discord.Embed(
            title=f"🏁 Season {season['season_id']} is over!",
            description="\n".join(lines) + f"\n\n👑 <@{podium[0]['user_id']}> is the new **champion**! A new season starts now.",
            color=discord.Color.gold(),
        )
        await self.bot.announcer.send(embed=embed)

    async def announce_teams(self, season: dict) -> None:
        podium = season["podium"]
        if not podium:
            return
        lines = []
        for p in podium:
            medal = MEDALS.get(p["rank"], f"#{p['rank']}")
            shares = ", ".join(f"<@{uid}> +{amount:,}" for uid, amount in p["payout"][:10])
            lines.append(
                f"{medal} **[{p['tag']}] {p['name']}** — {em(p['score'])} earned · "
                f"reward **{em(p['reward'])}**\n└ {shares}"
            )
        winner = podium[0]
        embed = discord.Embed(
            title=f"🛡️ Team season {season['season_id']} is over!",
            description="\n".join(lines) + f"\n\n🚩 **[{winner['tag']}] {winner['name']}** wins the team season!",
            color=discord.Color.gold(),
        )
        await self.bot.announcer.send(embed=embed)

    async def move_champion_role(self, champion_id: int | None) -> None:
        rid = role_id("season_champion")
        guild = self.bot.main_guild
        if not rid or guild is None:
            return
        role = guild.get_role(rid)
        if role is None:
            log.warning("roles.season_champion %s not found", rid)
            return
        try:
            for member in list(role.members):
                if member.id != champion_id:
                    await member.remove_roles(role, reason="Blocky season ended")
            if champion_id:
                member = guild.get_member(champion_id)
                if member is not None and role not in member.roles:
                    await member.add_roles(role, reason="Blocky season champion")
        except discord.HTTPException:
            log.exception("Could not move the champion role (check Manage Roles and role order)")

    @app_commands.command(name="season", description="Show this week's season standings.")
    async def season(self, interaction: discord.Interaction):
        data = await self.bot.db.run(seasons.overview, interaction.user.id)
        lines = [
            f"{MEDALS.get(i, f'`#{i}`')} {tag_prefix(data['tags'], uid)}<@{uid}> — **{em(score)}**"
            for i, (uid, score) in enumerate(data["top"], start=1)
        ]
        rewards = " · ".join(f"{MEDALS.get(i, f'#{i}')} {em(r)}" for i, r in enumerate(data["rewards"], start=1))
        embed = discord.Embed(
            title=f"🏆 Season {data['season_id']}",
            description=(
                "Score = value created this week: blocks mined, daily, drops, bosses, challenges...\n"
                f"Ends <t:{data['ends_at']}:R>. Rewards: {rewards or 'none'} + the champion role.\n\n"
                + ("\n".join(lines) or "Nobody has scored yet. Be the first!")
            ),
            color=discord.Color.gold(),
        )
        if data["champion"]:
            embed.add_field(name="👑 Current champion", value=f"<@{data['champion']}>", inline=True)
        embed.add_field(
            name="You",
            value=f"#{data['rank']} — {em(data['score'])}" if data["rank"] else "Not ranked yet",
            inline=True,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(SeasonsCog(bot))
