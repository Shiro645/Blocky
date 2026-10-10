from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from game import roulette, settings
from game.errors import GameError
from utils.checks import check_game_channel
from utils.ui import em

BET_CHOICES = [app_commands.Choice(name=label, value=key) for key, (label, _) in roulette.BETS.items()]
COLORS = {"red": "🟥", "black": "⬛", "green": "🟩"}


class RouletteCog(commands.Cog):
    """/roulette: a solo spin against the bank."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._next: dict[int, float] = {}  # user_id -> monotonic time of their next spin

    @app_commands.command(name="roulette", description="Spin the roulette: bet on a color, even/odd, a half, a dozen or a number.")
    @app_commands.describe(
        bet="What you bet on",
        amount="Emeralds you bet",
        number="Only for a bet on a number: 0, 00 or 1 to 36",
    )
    @app_commands.choices(bet=BET_CHOICES)
    async def roulette_cmd(
        self, interaction: discord.Interaction, bet: str, amount: app_commands.Range[int, 1],
        number: app_commands.Range[str, 1, 2] | None = None,
    ):
        check_game_channel(interaction)
        now = time.monotonic()
        ready = self._next.get(interaction.user.id, 0.0)
        if now < ready:
            raise GameError(f"The wheel is still turning: spin again in **{int(ready - now) + 1}s**.")
        if bet == "number" and number is None:
            raise GameError("Add the `number` option: 0, 00 or 1 to 36.")
        res = await self.bot.db.run(roulette.spin, interaction.user.id, bet, amount, number)
        self._next[interaction.user.id] = now + int(settings.get()["games"]["cooldown_seconds"])

        label = roulette.BETS[bet][0] + (f" {res['number']}" if bet == "number" else "")
        lines = [f"The ball lands on {COLORS[res['color']]} **{res['slot']}**.", f"Your bet: **{label}** · {em(amount)}"]
        if res["won"]:
            lines.append(f"🎉 You win **{em(res['payout'])}**!")
        else:
            lines.append("💸 Lost. Better luck next spin!")
        lines.append(f"Balance: {em(res['balance'])}")
        embed = discord.Embed(
            title="🎡 Roulette", description="\n".join(lines),
            color=discord.Color.green() if res["won"] else discord.Color.dark_grey(),
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(RouletteCog(bot))
