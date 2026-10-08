from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from database import (
    init_db,
    get_progress,
    spend_talent_point,
    xp_required_for_level,
    TALENT_BRANCHES,
)

from utils.config import load_emojis

EMOJI = load_emojis()

BRANCH_INFO = {
    "miner": "More/better blocks (higher gravel/deepslate odds + small bonus block chance).",
    "trader": "Better selling (bonus emeralds when you /sell).",
    "lucky": "Rarer finds (slightly higher bedrock chance on 1-block rolls).",
    "efficiency": "Faster gains (reduces message cooldown for block/xp gain).",
}

def _progress_bar(current: int, required: int, width: int = 14) -> str:
    if required <= 0:
        return "█" * width
    filled = int((current / required) * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)

class EconomyXPCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()

    @app_commands.command(name="xp", description="Show your XP, level and talent points.")
    async def xp(self, interaction: discord.Interaction):
        p = get_progress(interaction.user.id)
        req = xp_required_for_level(p["level"])
        bar = _progress_bar(p["xp"], req)

        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Progress",
            description=(
                f"Level **{p['level']}**\n"
                f"{EMOJI['xp']} XP: **{p['xp']} / {req}**\n"
                f"`{bar}`"
            ),
        )

        embed.add_field(
            name=f"Talent points",
            value=str(p["talent_points"]),
            inline=True,
        )
        embed.add_field(name="Miner", value=str(p["miner_points"]), inline=True)
        embed.add_field(name="Trader", value=str(p["trader_points"]), inline=True)
        embed.add_field(name="Lucky", value=str(p["lucky_points"]), inline=True)
        embed.add_field(name="Efficiency", value=str(p["efficiency_points"]), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="talents", description="Show talent branches and how they work.")
    async def talents(self, interaction: discord.Interaction):
        p = get_progress(interaction.user.id)

        lines = []
        for b in TALENT_BRANCHES:
            lines.append(f"**{b}**: {BRANCH_INFO[b]} (current: **{p[b + '_points']}**)")

        embed = discord.Embed(
            title="Talents",
            description="Spend your talent points to specialize your progression.\n\n" + "\n".join(lines),
        )

        embed.add_field(
            name=f"{EMOJI['xp']} Your talent points",
            value=str(p["talent_points"]),
            inline=False,
        )
        embed.add_field(
            name="How to spend",
            value="Use: `/talent_buy <branch> <points>`",
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="talent_buy", description="Spend talent points into a branch.")
    async def talent_buy(self, interaction: discord.Interaction, branch: str, points: int = 1):
        branch = branch.lower().strip()

        if branch not in TALENT_BRANCHES:
            return await interaction.response.send_message(
                f"❌ Invalid branch. Allowed: {', '.join(TALENT_BRANCHES)}",
                ephemeral=True,
            )

        if points <= 0:
            return await interaction.response.send_message(
                "❌ Points must be > 0.",
                ephemeral=True,
            )

        updated = spend_talent_point(interaction.user.id, branch, points)

        if updated is None:
            p = get_progress(interaction.user.id)
            return await interaction.response.send_message(
                f"❌ Not enough talent points. You have **{p['talent_points']} {EMOJI['xp']}**.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            f"✅ Spent **{points} {EMOJI['xp']}** into **{branch}**. Now: **{updated[branch + '_points']}**.",
            ephemeral=True,
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyXPCog(bot))
