from __future__ import annotations

import asyncio
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from game import roulette, settings
from game.errors import GameError
from utils.checks import check_game_channel
from utils.ui import em

SPIN_FRAMES = 3  # pictures of the turning wheel before the result
FRAME_SECONDS = 0.6


def bet_text(bet: str, number: str | None) -> str:
    return f"🎯 Number {number}" if bet == "number" else roulette.BETS[bet][0]


def strip(rng: random.Random, middle: str | None = None) -> str:
    """A piece of the wheel: 7 slots, the one under the arrow in the middle."""
    slots = roulette.slots()
    picks = [rng.choice(slots) for _ in range(7)]
    if middle is not None:
        picks[3] = middle
    blocks = [roulette.BLOCKS[roulette.color(s)][0] for s in picks]
    return " ".join(blocks[:3]) + f" ▶️{blocks[3]}◀️ " + " ".join(blocks[4:])


class RouletteCog(commands.Cog):
    """/wheel: a Minecraft roulette, a solo spin against the bank."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rng = random.Random()
        self._next: dict[int, float] = {}  # user_id -> monotonic time of their next spin

    async def bet_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        text = current.strip().lower()
        out = []
        for bet in roulette.open_bets():
            if bet == "number":
                continue
            label = f"{roulette.BETS[bet][0]} (×{roulette.payout(bet)})"
            if text in label.lower():
                out.append(app_commands.Choice(name=label, value=bet))
        if roulette.bet_open("number"):
            wanted = text.removeprefix("number").strip()
            for slot in roulette.slots():
                if not wanted or slot.startswith(wanted):
                    emoji, name = roulette.BLOCKS[roulette.color(slot)]
                    out.append(app_commands.Choice(name=f"🎯 Number {slot} — {emoji} {name} (×36)", value=f"number:{slot}"))
        return out[:25]

    @app_commands.command(name="wheel", description="Spin the Minecraft wheel: bet on Redstone, Obsidian or a number!")
    @app_commands.describe(bet="What you bet on: pick a suggestion, or type a number (0, 00, 1 to 36)",
                           amount="Emeralds you bet")
    @app_commands.autocomplete(bet=bet_autocomplete)
    async def wheel_cmd(self, interaction: discord.Interaction, bet: str, amount: app_commands.Range[int, 1]):
        check_game_channel(interaction)
        bet, _, number = bet.strip().partition(":")
        if bet.isdigit():  # a number typed without picking the suggestion
            bet, number = "number", bet
        bet = {"redstone": "red", "obsidian": "black", "diamond": "green"}.get(bet.lower(), bet.lower())
        now = time.monotonic()
        ready = self._next.get(interaction.user.id, 0.0)
        if now < ready:
            raise GameError(f"The wheel is still turning: spin again in **{int(ready - now) + 1}s**.")
        # Reserved before the await: a second command sent at the same time waits for the cooldown.
        self._next[interaction.user.id] = now + int(settings.get()["games"]["cooldown_seconds"])
        try:
            res = await self.bot.db.run(roulette.spin, interaction.user.id, bet, amount, number or None)
        except BaseException:
            self._next[interaction.user.id] = ready  # nothing was played: no cooldown
            raise

        title = "🎡 The wheel"
        head = f"Your bet: **{bet_text(bet, res['number'])}** · {em(amount)}"
        spinning = discord.Embed(title=title, description=f"{head}\n\n{strip(self.rng)}\n*The wheel is spinning…*",
                                 color=discord.Color.gold())
        spinning.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=spinning)
        try:
            for n in range(SPIN_FRAMES - 1):
                await asyncio.sleep(FRAME_SECONDS)
                spinning.description = f"{head}\n\n{strip(self.rng)}\n*The wheel is {'slowing down' if n else 'spinning'}…*"
                await interaction.edit_original_response(embed=spinning)
            await asyncio.sleep(FRAME_SECONDS)
        except discord.HTTPException:
            pass

        lines = [head, "", strip(self.rng, res["slot"]), f"The wheel stops on **{roulette.slot_label(res['slot'])}**."]
        lines.append(f"🎉 You win **{em(res['payout'])}**!" if res["won"] else "💸 Lost. Better luck next spin!")
        lines.append(f"Balance: {em(res['balance'])}")
        embed = discord.Embed(title=title, description="\n".join(lines),
                              color=discord.Color.green() if res["won"] else discord.Color.dark_grey())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        try:
            await interaction.edit_original_response(embed=embed)
        except discord.HTTPException:
            await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(RouletteCog(bot))
