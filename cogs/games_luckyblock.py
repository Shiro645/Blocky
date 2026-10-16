from __future__ import annotations

import asyncio
import time

import discord
from discord import app_commands
from discord.ext import commands

from game import luckyblock, settings
from game.errors import GameError
from utils.checks import check_game_channel
from utils.ui import em


# The block breaking, frame by frame (monospace art), before the result.
FRAMES = (
    r"""
     ________
    /       /|
   /  ???  / |
  /_______/  |
  |       |  |
  |  ???  |  /
  |       | /
  |_______|/
""",
    r"""
     ________
    /   ,   /|
   /  ?\?  / |
  /___/___/  |
  |   \   |  |
  |  ?/?  |  /
  |   \   | /
  |_______|/
""",
    r"""
     __  ____
    / \/ /\ /|
   / ?\ ?/ / |
  /_/\_/\_/  |
  |\ /\ / |  |
  | X  X  |  /
  |/ \/ \ | /
  |_/\__\_|/
""",
    r"""
   \   .   |   .   /
  .  \   \ | /   /  .
 -  -  - POP! -  -  -
  .  /   / | \   \  .
   /   .   |   .   \
""",
)
CAPTIONS = ("*Mining the Lucky Block…*", "*It's cracking…*", "*Almost…*", "*POP!*")
FRAME_SECONDS = 0.7


def frame_embed(user: discord.abc.User, amount: int, n: int) -> discord.Embed:
    embed = discord.Embed(title="🟨❓ Lucky Block", color=discord.Color.yellow(),
                          description=f"```{FRAMES[n]}```{CAPTIONS[n]} (bet {em(amount)})")
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    return embed


def result_embed(user: discord.abc.User, res: dict) -> discord.Embed:
    o, amount, won = res["outcome"], res["amount"], res["won"]
    lines = [f"*{o.text}*", ""]
    if won > amount:
        lines.append(f"🎉 You win **{em(won)}** (×{res['payout']:g}): **+{em(won - amount)}**")
    elif won == amount:
        lines.append(f"Your bet back: {em(won)}")
    elif won:
        lines.append(f"You get {em(won)} back (−{em(amount - won)})")
    else:
        lines.append(f"💸 Lost: {em(amount)}")
    lines.append(f"Balance: {em(res['balance'])}")
    color = (discord.Color.gold() if o.key == "netherite" else discord.Color.green() if won > amount
             else discord.Color.dark_grey())
    embed = discord.Embed(title=f"{o.emoji} {o.name}!", description="\n".join(lines), color=color)
    embed.set_author(name=f"{user.display_name} breaks a Lucky Block", icon_url=user.display_avatar.url)
    cap = res["cap"]
    if cap:
        net = res["net_today"]
        embed.set_footer(text=f"Today at games of chance: {'+' if net >= 0 else ''}{net:,} (you can win {cap:,} a day)")
    return embed


class LuckyBlockCog(commands.Cog):
    """/luckyblock: bet emeralds, break the block, see what falls out."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._next: dict[int, float] = {}  # user_id -> monotonic time of their next block

    @app_commands.command(name="luckyblock", description="Bet emeralds and break a Lucky Block: anything can fall out!")
    @app_commands.describe(amount="Emeralds you bet")
    async def luckyblock_cmd(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1]):
        check_game_channel(interaction)
        now = time.monotonic()
        ready = self._next.get(interaction.user.id, 0.0)
        if now < ready:
            raise GameError(f"Your pickaxe needs a break: try again in **{int(ready - now) + 1}s**.")
        # Reserved before the await: a second command sent at the same time waits for the cooldown.
        self._next[interaction.user.id] = now + int(settings.get()["games"]["cooldown_seconds"])
        try:
            res = await self.bot.db.run(luckyblock.open_block, interaction.user.id, amount)
        except BaseException:
            self._next[interaction.user.id] = ready  # nothing was played: no cooldown
            raise
        await interaction.response.send_message(embed=frame_embed(interaction.user, amount, 0))
        try:
            for n in range(1, len(FRAMES)):
                await asyncio.sleep(FRAME_SECONDS)
                await interaction.edit_original_response(embed=frame_embed(interaction.user, amount, n))
            await asyncio.sleep(FRAME_SECONDS)
        except discord.HTTPException:
            pass
        try:
            await interaction.edit_original_response(embed=result_embed(interaction.user, res))
        except discord.HTTPException:
            await interaction.followup.send(embed=result_embed(interaction.user, res))


async def setup(bot: commands.Bot):
    await bot.add_cog(LuckyBlockCog(bot))
