from __future__ import annotations

import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import blackjack, gambling, settings
from game.errors import GameError
from utils.checks import check_game_channel
from utils.ui import em, report_error

log = logging.getLogger("blackjack")

RESULTS = {
    "blackjack": ("🃏 **Blackjack!**", discord.Color.gold()),
    "win": ("🎉 **You win!**", discord.Color.green()),
    "push": ("🤝 **Push**: your bet back.", discord.Color.light_grey()),
    "lose": ("💸 **The dealer wins.**", discord.Color.dark_grey()),
    "bust": ("💥 **Over 21**: you lose.", discord.Color.dark_grey()),
}


def cards(hand: list[str], hide_second: bool = False) -> str:
    shown = [f"`{c}`" for c in hand]
    if hide_second and len(shown) > 1:
        shown[1] = "`🂠`"
    return " ".join(shown)


def game_embed(game: dict, user: discord.abc.User | None = None) -> discord.Embed:
    state, over = game["state"], game["status"] == "done"
    player, dealer = state["player"], state["dealer"]
    dealer_total = blackjack.value(dealer) if over else blackjack.value(dealer[:1])
    lines = [
        f"**Dealer** — {cards(dealer, hide_second=not over)} · **{dealer_total}**{'' if over else ' + ?'}",
        f"**You** — {cards(player)} · **{blackjack.value(player)}**",
        "",
        f"Bet: {em(game['bet'])}" + (" (doubled)" if state["doubled"] else ""),
    ]
    color = discord.Color.blurple()
    if over:
        text, color = RESULTS.get(game["result"], ("Over.", discord.Color.dark_grey()))
        gain = game["paid"] - game["bet"]
        lines.append(f"{text} " + (f"**+{em(gain)}**" if gain > 0 else f"**−{em(-gain)}**" if gain < 0 else ""))
        if "balance" in game:
            lines.append(f"Balance: {em(game['balance'])}")
    else:
        lines.append(f"*Hit, stand or double* (no move <t:{game['deadline']}:R>: you stand)")
    embed = discord.Embed(title="🃏 Blackjack", description="\n".join(lines), color=color)
    if user is not None:
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    return embed


class BlackjackButton(discord.ui.DynamicItem[discord.ui.Button],
                      template=r"blocky:bj:(?P<action>hit|stand|double):(?P<game_id>\d+)"):
    """Hit / Stand / Double. They survive restarts; only the player can use them."""

    LOOK = {"hit": ("Hit", "🃏", discord.ButtonStyle.primary),
            "stand": ("Stand", "✋", discord.ButtonStyle.secondary),
            "double": ("Double", "💰", discord.ButtonStyle.success)}

    def __init__(self, action: str, game_id: int, disabled: bool = False) -> None:
        label, emoji, style = self.LOOK[action]
        super().__init__(discord.ui.Button(label=label, emoji=emoji, style=style, disabled=disabled,
                                           custom_id=f"blocky:bj:{action}:{game_id}"))
        self.action, self.game_id = action, game_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(match["action"], int(match["game_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            fn = {"hit": blackjack.hit, "stand": blackjack.stand, "double": blackjack.double}[self.action]
            game = await interaction.client.db.run(fn, self.game_id, interaction.user.id)  # type: ignore[attr-defined]
            await interaction.response.edit_message(embed=game_embed(game, interaction.user), view=game_view(game))
        except Exception as error:
            await report_error(interaction, error)


def game_view(game: dict) -> discord.ui.View | None:
    if game["status"] != "active":
        return None
    view = discord.ui.View(timeout=None)
    view.add_item(BlackjackButton("hit", game["game_id"]))
    view.add_item(BlackjackButton("stand", game["game_id"]))
    view.add_item(BlackjackButton("double", game["game_id"], disabled=not blackjack.can_double(game)))
    return view


class BlackjackCog(commands.Cog):
    """/blackjack: a hand against the dealer."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._next: dict[int, float] = {}  # user_id -> monotonic time of their next game

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(BlackjackButton)
        self.expire_loop.start()

    async def cog_unload(self) -> None:
        self.expire_loop.cancel()
        self.bot.remove_dynamic_items(BlackjackButton)

    @app_commands.command(name="blackjack", description="Play a hand of blackjack against the dealer.")
    @app_commands.describe(amount="Emeralds you bet")
    async def blackjack_cmd(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1]):
        check_game_channel(interaction)
        now = time.monotonic()
        ready = self._next.get(interaction.user.id, 0.0)
        if now < ready:
            raise GameError(f"The dealer is shuffling: play again in **{int(ready - now) + 1}s**.")
        self._next[interaction.user.id] = now + int(settings.get()["games"]["cooldown_seconds"])
        try:
            game = await self.bot.db.run(blackjack.start, interaction.user.id, amount)
        except BaseException:
            self._next[interaction.user.id] = ready  # nothing was played: no cooldown
            raise
        await interaction.response.send_message(embed=game_embed(game, interaction.user), view=game_view(game))
        if game["status"] == "active":
            message = await interaction.original_response()
            await self.bot.db.run(gambling.set_message, game["game_id"], message.channel.id, message.id)

    @tasks.loop(minutes=1)
    async def expire_loop(self):
        try:
            for game in await self.bot.db.run(blackjack.expire):
                await self.show(game)
        except Exception:  # an error must never stop the loop
            log.exception("Blackjack loop failed")

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
            log.warning("Could not update a blackjack message", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BlackjackCog(bot))
