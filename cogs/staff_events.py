from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from game.errors import GameError
from utils.checks import staff_only


class StaffEventsCog(commands.Cog):
    """/event: start the server events now. The work is done by each event's own cog."""

    event = app_commands.Group(name="event", description="STAFF: Start an event now: boss, drop, tournament, villager.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def cog(self, name: str) -> Any:
        cog = self.bot.get_cog(name)
        if cog is None:
            raise GameError("This feature isn't loaded right now (see the bot logs).")
        return cog

    @event.command(name="boss", description="STAFF: Summon a boss now (one at a time).")
    @app_commands.describe(name="Boss name (random if empty)", hp="Health points (default from the settings)")
    @staff_only()
    async def boss(
        self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 64] | None = None,
        hp: app_commands.Range[int, 1, 10_000_000] | None = None,
    ):
        await self.cog("BossCog").summon(interaction, name, hp)

    @event.command(name="drop", description="STAFF: Make a drop appear in this channel now.")
    @staff_only()
    async def drop(self, interaction: discord.Interaction):
        await self.cog("DropsCog").staff_spawn(interaction)

    @event.command(name="tournament", description="STAFF: Open, advance or cancel the weekend tournament now.")
    @app_commands.describe(action="What to do")
    @app_commands.choices(action=[
        app_commands.Choice(name="Open registrations now", value="open"),
        app_commands.Choice(name="Next step now (draw, then next round)", value="next"),
        app_commands.Choice(name="Cancel and refund", value="cancel"),
    ])
    @staff_only()
    async def tournament(self, interaction: discord.Interaction, action: str):
        await self.cog("TournamentCog").staff_action(interaction, action)

    @event.command(name="villager", description="STAFF: Make the wandering villager come now, or leave.")
    @app_commands.describe(action="What to do")
    @app_commands.choices(action=[
        app_commands.Choice(name="Come now (usual visit length)", value="come"),
        app_commands.Choice(name="Leave now", value="leave"),
    ])
    @staff_only()
    async def villager(self, interaction: discord.Interaction, action: str):
        await self.cog("VillagerCog").staff_action(interaction, action)


async def setup(bot: commands.Bot):
    await bot.add_cog(StaffEventsCog(bot))
