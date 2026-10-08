from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import leaderboard, players
from game.catalog import TALENT_BRANCHES
from utils.ui import em, gear_label, join_lines, progress_bar

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

BOARD_CHOICES = [app_commands.Choice(name=label, value=key) for key, (label, _) in leaderboard.BOARDS.items()]

PROFILE_STATS = [
    ("blocks_mined", "⛏️ Blocks mined"),
    ("bedrock_found", "🟪 Bedrock found"),
    ("emeralds_earned", "💰 Emeralds earned"),
    ("items_crafted", "🛠️ Items crafted"),
    ("duels_won", "⚔️ Duels won"),
    ("duels_lost", "💀 Duels lost"),
    ("best_streak", "🔥 Best daily streak"),
    ("seasons_won", "👑 Seasons won"),
    ("season_podiums", "🏅 Season podiums"),
]


def format_value(board: str, value: int, plain: bool = False) -> str:
    """`plain` for footers, where custom emojis are not rendered."""
    unit = leaderboard.BOARDS[board][1]
    if unit == "emerald":
        return f"{value:,} emeralds" if plain else em(value)
    if unit == "level":
        return f"level {value}"
    return f"{value:,}"


def rank_text(rank: int | None) -> str:
    return f"#{rank}" if rank else "unranked"


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="leaderboard", description="Show the server rankings.")
    @app_commands.describe(board="What to rank players by")
    @app_commands.choices(board=BOARD_CHOICES)
    async def leaderboard_cmd(self, interaction: discord.Interaction, board: str = "fortune"):
        data = await self.bot.db.run(leaderboard.leaderboard, board, interaction.user.id)

        lines = [
            f"{MEDALS.get(i, f'`#{i}`')} <@{uid}> — **{format_value(board, value)}**"
            for i, (uid, value) in enumerate(data["top"], start=1)
        ]
        embed = discord.Embed(
            title=f"🏆 Leaderboard — {leaderboard.BOARDS[board][0]}",
            description="\n".join(lines) or "Nobody is ranked yet. Start playing!",
            color=discord.Color.gold(),
        )
        if data["rank"]:
            embed.set_footer(
                text=f"Your rank: #{data['rank']} of {data['players']} — {format_value(board, data['value'], plain=True)}"
            )
        else:
            embed.set_footer(text="You are not ranked yet.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="profile", description="Show a player's profile.")
    @app_commands.describe(member="Player to look at (yourself by default)")
    async def profile(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        if target.bot:
            return await interaction.response.send_message("❌ Bots don't play.", ephemeral=True)
        p = await self.bot.db.run(leaderboard.profile, target.id)
        embed = self.build_profile_embed(target, p)
        await interaction.response.send_message(embed=embed)

    def build_profile_embed(self, target: discord.abc.User, p: dict) -> discord.Embed:
        u = p["user"]
        req = players.xp_required_for_level(u["level"])
        title = f"{target.display_name}'s profile"
        if p["is_champion"]:
            title = "👑 " + title + " — Season champion"
        embed = discord.Embed(
            title=title,
            description=(
                f"**Level {u['level']}** ({rank_text(p['level_rank'])}) — {u['xp']}/{req} XP\n"
                f"`{progress_bar(u['xp'], req)}`"
            ),
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Emeralds", value=em(u["emeralds"]), inline=True)
        embed.add_field(name="Fortune", value=f"{em(p['fortune'])} ({rank_text(p['fortune_rank'])})", inline=True)
        talents = " · ".join(f"{b} {u[b + '_points']}" for b in TALENT_BRANCHES)
        embed.add_field(name="Talents", value=talents, inline=False)

        equipped = join_lines([gear_label(g) for g in p["equipped"]], empty="Nothing equipped.")
        embed.add_field(name="Equipment", value=equipped, inline=False)

        unlocked = p["achievements"]["unlocked"]
        total = len(unlocked) + len(p["achievements"]["locked"])
        icons = " ".join(a.icon for a, _ in unlocked[-12:])
        embed.add_field(name=f"Achievements ({len(unlocked)}/{total})", value=icons or "None yet.", inline=False)

        stats = "\n".join(f"{label}: **{p['stats'].get(key, 0):,}**" for key, label in PROFILE_STATS)
        embed.add_field(name="Stats", value=stats, inline=False)
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
