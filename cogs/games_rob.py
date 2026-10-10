from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import robbery, settings
from game.errors import GameError
from utils.checks import check_game_channel
from utils.ui import dm, em, report_error

log = logging.getLogger("rob")

MODE_CHOICES = [
    app_commands.Choice(name="Risky: they get pinged, big loot", value="risky"),
    app_commands.Choice(name="Discreet: no ping, small loot", value="discreet"),
]


def rob_embed(rob: dict) -> discord.Embed:
    thief, victim = f"<@{rob['thief_id']}>", f"<@{rob['victim_id']}>"
    risky = rob["mode"] == "risky"
    if rob["status"] == "stopped":
        fine = f" and paid a fine of {em(rob['fine'])}" if rob["fine"] else ""
        return discord.Embed(title="🛡️ Robbery stopped!", color=discord.Color.green(),
                             description=f"{victim} caught {thief} in the act{fine}.")
    if rob["status"] == "done":
        return discord.Embed(title="💰 Robbery done", color=discord.Color.dark_red(),
                             description=f"{thief} got away with {em(rob['stolen'])} from {victim}.")
    title = "🦹 Robbery in progress!" if risky else "🤫 A discreet robbery…"
    text = (f"{thief} is robbing {victim}!" if risky else f"{thief} is quietly emptying {victim}'s pockets…")
    text += f"\n{victim} can stop it until <t:{rob['ends_at']}:t> (<t:{rob['ends_at']}:R>) with the button below."
    return discord.Embed(title=title, description=text, color=discord.Color.orange() if risky else discord.Color.dark_grey())


class StopRobButton(discord.ui.DynamicItem[discord.ui.Button], template=r"blocky:rob:(?P<rob_id>\d+)"):
    """The victim's button. It survives restarts."""

    def __init__(self, rob_id: int, disabled: bool = False) -> None:
        super().__init__(discord.ui.Button(label="Stop the thief!", emoji="🛡️", style=discord.ButtonStyle.success,
                                           custom_id=f"blocky:rob:{rob_id}", disabled=disabled))
        self.rob_id = rob_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["rob_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            rob = await interaction.client.db.run(robbery.stop, self.rob_id, interaction.user.id)  # type: ignore[attr-defined]
            await interaction.response.edit_message(embed=rob_embed(rob), view=rob_view(rob))
        except Exception as error:
            await report_error(interaction, error)


def rob_view(rob: dict) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(StopRobButton(rob["rob_id"], disabled=rob["status"] != "active"))
    return view


class RobCog(commands.Cog):
    """/rob: steal emeralds from a player, who has some time to stop you."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(StopRobButton)
        self.rob_loop.start()

    async def cog_unload(self) -> None:
        self.rob_loop.cancel()

    @app_commands.command(name="rob", description="Rob a player: they have some time to stop you. Risky = big loot, discreet = no ping.")
    @app_commands.describe(member="Who you rob", mode="Risky (they get pinged, big loot) or discreet (no ping, small loot)")
    @app_commands.choices(mode=MODE_CHOICES)
    async def rob(self, interaction: discord.Interaction, member: discord.Member, mode: str):
        check_game_channel(interaction)
        if member.bot:
            raise GameError("Bots have nothing worth stealing.")
        rob = await self.bot.db.run(robbery.start, interaction.user.id, member.id, mode)
        risky = mode == "risky"
        await interaction.response.send_message(
            content=member.mention if risky else None,
            embed=rob_embed(rob), view=rob_view(rob),
            # Risky pings the victim; discreet pings nobody.
            allowed_mentions=discord.AllowedMentions(users=[member]) if risky else discord.AllowedMentions.none(),
        )
        message = await interaction.original_response()
        await self.bot.db.run(robbery.set_message, rob["rob_id"], message.channel.id, message.id)

    # ---------- background ----------
    @tasks.loop(minutes=1)
    async def rob_loop(self):
        try:
            for rob in await self.bot.db.run(robbery.finish_due):
                await self.finished(rob)
        except Exception:  # an error must never stop the loop
            log.exception("Rob loop failed")

    @rob_loop.before_loop
    async def before_rob_loop(self):
        await self.bot.wait_until_ready()

    async def finished(self, rob: dict) -> None:
        """A robbery nobody stopped: update its message and tell the victim."""
        channel = self.bot.get_channel(rob["channel_id"] or 0)
        if channel is not None and rob["message_id"]:
            try:
                message = await channel.fetch_message(rob["message_id"])  # type: ignore[union-attr]
                await message.edit(content=None, embed=rob_embed(rob), view=rob_view(rob))
            except discord.HTTPException:
                pass
        guild = self.bot.main_guild  # type: ignore[attr-defined]
        victim = self.bot.get_user(rob["victim_id"])
        if victim is not None and rob["stolen"]:
            where = f" on **{guild.name}**" if guild else ""
            thief = self.bot.get_user(rob["thief_id"])
            name = thief.display_name if thief else "Someone"
            await dm(victim, f"🦹 {name} robbed you of {em(rob['stolen'])}{where}. "
                             f"You're safe from robberies for {settings.get()['rob']['victim_protection_hours']} h.")


async def setup(bot: commands.Bot):
    await bot.add_cog(RobCog(bot))
