from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from cogs.player_profile import card_file
from game import leaderboard, players, profiles, species
from game.catalog import TALENT_BRANCHES
from utils.ui import em, gear_label, join_lines, progress_bar, tag_prefix

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

BOARD_CHOICES = [app_commands.Choice(name=label, value=key) for key, (label, _) in leaderboard.BOARDS.items()]

PROFILE_STATS = [
    ("blocks_mined", "⛏️ Blocks mined"),
    ("bedrock_found", "🟪 Bedrock found"),
    ("obsidian_found", "🟣 Obsidian found"),
    ("emeralds_earned", "💰 Emeralds earned"),
    ("items_crafted", "🛠️ Items crafted"),
    ("duels_won", "⚔️ Duels won"),
    ("duels_lost", "💀 Duels lost"),
    ("tournaments_won", "🏟️ Tournaments won"),
    ("boss_damage", "🐉 Boss damage"),
    ("beacon_value", "🔆 Given to the Beacon"),
    ("drops_claimed", "🎁 Drops claimed"),
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
            f"{MEDALS.get(i, f'`#{i}`')} {tag_prefix(data['tags'], uid, data['species'])}<@{uid}> — **{format_value(board, value)}**"
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
        file = await card_file(target, p)
        embed = self.build_profile_embed(target, p, card=file is not None)
        if file is None:
            await interaction.response.send_message(embed=embed)
        else:
            # The card first: an embed's image always comes under its fields, so it gets its own embed above.
            card = discord.Embed(color=embed.color)
            card.set_image(url="attachment://profile.png")
            await interaction.response.send_message(embeds=[card, embed], file=file)
        await self.bot.db.run(players.bump_stat, interaction.user.id, "profiles_viewed")  # a guide step

    def build_profile_embed(self, target: discord.abc.User, p: dict, card: bool = False) -> discord.Embed:
        """The details under the card (with `card`), or the whole profile as text (without Pillow)."""
        u = p["user"]
        req = players.xp_required_for_level(u["level"])
        color = discord.Color.from_rgb(*profiles.color_rgb(p["custom"]["color"]))
        if card:
            embed = discord.Embed(color=color)
        else:
            title = f"{target.display_name}'s profile"
            if p["team"]:
                title = f"[{p['team']['tag']}] " + title
            if p["is_champion"]:
                title = "👑 " + title + " — Season champion"
            label = profiles.title_label(p["custom"]["title"])
            embed = discord.Embed(
                title=title,
                description=(
                    (f"« {label} »\n" if label else "")
                    + (f"*{p['custom']['bio']}*\n" if p["custom"]["bio"] else "")
                    + f"**Level {u['level']}** ({rank_text(p['level_rank'])}) — {u['xp']}/{req} XP\n"
                    f"`{progress_bar(u['xp'], req)}`"
                ),
                color=color,
            )
            embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Emeralds", value=em(u["emeralds"]), inline=True)
        embed.add_field(name="Fortune", value=f"{em(p['fortune'])} ({rank_text(p['fortune_rank'])})", inline=True)
        if p["link"] and p["link"]["status"] == "approved":
            embed.add_field(name="Minecraft", value=f"🔗 {p['link']['mc_username']}", inline=True)
        if p["team"]:
            leader = " 👑" if p["team"]["leader_id"] == target.id else ""
            embed.add_field(name="Team", value=f"🛡️ [{p['team']['tag']}] {p['team']['name']}{leader}", inline=True)
        kind = u.get("species")
        embed.add_field(
            name="Species",
            value=f"{species.label(kind)} — {species.describe(kind)}" if kind in species.SPECIES
            else "None yet: `/species choose`",
            inline=False,
        )
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
