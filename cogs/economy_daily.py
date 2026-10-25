from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import daily, players, settings
from utils.ui import EMOJI, em, mat


class DailyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="daily", description="Claim your daily reward. Come back every day to grow your streak!")
    async def daily_cmd(self, interaction: discord.Interaction):
        res = await self.bot.db.run(daily.claim, interaction.user.id)
        cap = settings.get()["daily"]["streak_cap_days"]

        flames = "🔥" * min(res["streak"], cap)
        lines = [
            f"+{em(res['emeralds'])}  ·  {players.xp_text(res['xp'], res.get('mended', 0))} {EMOJI['xp']}".rstrip(),
            f"Streak: **{res['streak']} day{'s' if res['streak'] > 1 else ''}** {flames}",
        ]
        if res.get("rested"):
            lines.append(f"🛏️ Well rested: **+{float(settings.get()['night']['sleep_daily_bonus']):.0%}** for sleeping "
                         "last night (`/sleep`).")
        if res["bonus_item"]:
            every = settings.get()["daily"]["bonus_every_days"]
            lines.append(f"🎁 {every}-day bonus: {mat(res['bonus_item'])} **1 {res['bonus_item']} ingot**!")
        if res["lost_streak"]:
            lines.append(f"💔 You lost your {res['lost_streak']}-day streak. Don't miss a day!")
        lines.append(f"Tomorrow: **{em(res['next_reward'])}**")

        embed = discord.Embed(title="📅 Daily reward", description="\n".join(lines), color=discord.Color.green())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)  # public: rewards are shown to everyone


async def setup(bot: commands.Bot):
    await bot.add_cog(DailyCog(bot))
