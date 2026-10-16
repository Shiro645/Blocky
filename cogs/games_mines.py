from __future__ import annotations

import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import gambling, mines, settings
from game.errors import GameError
from utils.checks import check_game_channel
from utils.ui import em, report_error

log = logging.getLogger("mines")

ROW = 5  # blocks per row of buttons


def game_embed(game: dict, user: discord.abc.User | None = None) -> discord.Embed:
    state = game["state"]
    tnt, dug = len(state["tnt"]), len(state["dug"])
    lines = [f"Bet: {em(game['bet'])} · 🧨 **{tnt}** TNT hidden in {mines.CELLS} blocks · ⛏️ **{dug}** dug"]
    color = discord.Color.blurple()
    if game["status"] == "active":
        if dug:
            lines.append(f"Cash out now: **×{mines.multiplier(dug, tnt):.2f}** = **{em(mines.payout(game))}**")
        nxt = mines.multiplier(dug + 1, tnt)
        lines.append(f"Next safe block: **×{nxt:.2f}**")
        lines.append(f"*Dig a block or cash out* (no move <t:{game['deadline']}:R>: you cash out)")
    elif game["result"] == "boom":
        lines.append(f"💥 **BOOM!** You hit the TNT: −{em(game['bet'])}")
        color = discord.Color.dark_grey()
    elif game["result"] == "refunded":
        lines.append("⏳ Nothing dug in time: your bet is back.")
        color = discord.Color.light_grey()
    else:
        gain = game["paid"] - game["bet"]
        lines.append(f"💰 Cashed out at **×{mines.multiplier(dug, tnt):.2f}**: {em(game['paid'])} "
                     + (f"(**+{em(gain)}**)" if gain > 0 else f"(−{em(-gain)})" if gain < 0 else ""))
        color = discord.Color.green() if gain > 0 else discord.Color.dark_grey()
    embed = discord.Embed(title="💣 Mines", description="\n".join(lines), color=color)
    if user is not None:
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    return embed


class MinesButton(discord.ui.DynamicItem[discord.ui.Button],
                  template=r"blocky:mines:(?P<game_id>\d+):(?P<cell>\d+|cash)"):
    """A block to dig, or the cash out button. They survive restarts; only the player can use them."""

    def __init__(self, game_id: int, cell: str, *, emoji: str | None = None, label: str | None = None,
                 style: discord.ButtonStyle = discord.ButtonStyle.secondary, disabled: bool = False,
                 row: int | None = None) -> None:
        super().__init__(discord.ui.Button(emoji=emoji, label=label, style=style, disabled=disabled, row=row,
                                           custom_id=f"blocky:mines:{game_id}:{cell}"))
        self.game_id, self.cell = game_id, cell

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["game_id"]), match["cell"])

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            db = interaction.client.db  # type: ignore[attr-defined]
            if self.cell == "cash":
                game = await db.run(mines.cash_out, self.game_id, interaction.user.id)
            else:
                game = await db.run(mines.dig, self.game_id, interaction.user.id, int(self.cell))
            await interaction.response.edit_message(embed=game_embed(game, interaction.user), view=game_view(game))
        except Exception as error:
            await report_error(interaction, error)


def game_view(game: dict) -> discord.ui.View:
    """The 20 blocks (dug ones show what was in them; at the end the TNT shows) and the cash out button."""
    state, over = game["state"], game["status"] != "active"
    view = discord.ui.View(timeout=None)
    for cell in range(mines.CELLS):
        if cell == state.get("boom"):
            emoji, style = "💥", discord.ButtonStyle.danger
        elif cell in state["dug"]:
            emoji, style = "💎", discord.ButtonStyle.success
        elif over and cell in state["tnt"]:
            emoji, style = "🧨", discord.ButtonStyle.secondary
        else:
            emoji, style = "🟫", discord.ButtonStyle.secondary
        view.add_item(MinesButton(game["game_id"], str(cell), emoji=emoji, style=style, row=cell // ROW,
                                  disabled=over or cell in state["dug"]))
    if not over:
        dug = len(state["dug"])
        label = f"Cash out · {mines.payout(game):,}" if dug else "Cash out"
        view.add_item(MinesButton(game["game_id"], "cash", emoji="💰", label=label, row=4,
                                  style=discord.ButtonStyle.primary, disabled=not dug))
    return view


class MinesCog(commands.Cog):
    """/mines: dig blocks, avoid the TNT, cash out in time."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._next: dict[int, float] = {}  # user_id -> monotonic time of their next game

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(MinesButton)
        self.expire_loop.start()

    async def cog_unload(self) -> None:
        self.expire_loop.cancel()
        self.bot.remove_dynamic_items(MinesButton)

    @app_commands.command(name="mines", description="Dig blocks for emeralds without hitting the TNT. Cash out in time!")
    @app_commands.describe(amount="Emeralds you bet", tnt="TNT hidden in the 20 blocks: more TNT, bigger multipliers")
    async def mines_cmd(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1],
                        tnt: app_commands.Range[int, 1, 19] = 3):
        check_game_channel(interaction)
        now = time.monotonic()
        ready = self._next.get(interaction.user.id, 0.0)
        if now < ready:
            raise GameError(f"Catch your breath: play again in **{int(ready - now) + 1}s**.")
        self._next[interaction.user.id] = now + int(settings.get()["games"]["cooldown_seconds"])
        try:
            game = await self.bot.db.run(mines.start, interaction.user.id, amount, tnt)
        except BaseException:
            self._next[interaction.user.id] = ready  # nothing was played: no cooldown
            raise
        await interaction.response.send_message(embed=game_embed(game, interaction.user), view=game_view(game))
        message = await interaction.original_response()
        await self.bot.db.run(gambling.set_message, game["game_id"], message.channel.id, message.id)

    @tasks.loop(minutes=1)
    async def expire_loop(self):
        try:
            for game in await self.bot.db.run(mines.expire):
                await self.show(game)
        except Exception:  # an error must never stop the loop
            log.exception("Mines loop failed")

    @expire_loop.before_loop
    async def before_expire_loop(self):
        await self.bot.wait_until_ready()

    async def show(self, game: dict) -> None:
        channel = self.bot.get_channel(game["channel_id"] or 0)
        if not isinstance(channel, discord.abc.Messageable) or not game["message_id"]:
            return
        try:
            await channel.get_partial_message(game["message_id"]).edit(embed=game_embed(game), view=game_view(game))
        except discord.HTTPException:
            log.warning("Could not update a mines message", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MinesCog(bot))
