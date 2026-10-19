from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from game import live_events
from game.errors import GameError
from utils.checks import staff_only


class StaffEventsCog(commands.Cog):
    """/event: start the server events now. The work is done by each event's own cog."""

    event = app_commands.Group(name="event", description="STAFF: Start an event now: timed event, drop, quiz, tournament, villager, Beacon.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def cog(self, name: str) -> Any:
        cog = self.bot.get_cog(name)
        if cog is None:
            raise GameError("This feature isn't loaded right now (see the bot logs).")
        return cog

    @event.command(name="start", description="STAFF: Start a timed event now (Gambling Frenzy, Mining Rush…).")
    @app_commands.describe(kind="Which event", minutes="How long (default from /config → Timed events)")
    @app_commands.rename(kind="event")
    @app_commands.choices(kind=[app_commands.Choice(name=k.label, value=key) for key, k in live_events.KINDS.items()])
    @staff_only()
    async def start(self, interaction: discord.Interaction, kind: str,
                    minutes: app_commands.Range[int, 1, 1440] | None = None):
        await self.cog("LiveEventsCog").staff_start(interaction, kind, minutes)

    @event.command(name="stop", description="STAFF: End the timed event that is on now.")
    @staff_only()
    async def stop(self, interaction: discord.Interaction):
        await self.cog("LiveEventsCog").staff_stop(interaction)

    @event.command(name="beacon", description="STAFF: Light or put out the server's Beacon, or set its steps built.")
    @app_commands.describe(lit="Lit (as if the Wither was beaten) or not", step="Steps built, 0-16 (empty = unchanged)")
    @staff_only()
    async def beacon(self, interaction: discord.Interaction, lit: bool, step: app_commands.Range[int, 0, 16] | None = None):
        await self.cog("BeaconCog").staff_set(interaction, lit, step)

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

    @event.command(name="quiz", description="STAFF: Ask a Minecraft quiz question in this channel now.")
    @staff_only()
    async def quiz(self, interaction: discord.Interaction):
        quiz_cog = self.cog("QuizCog")
        await interaction.response.send_message("✅ Question posted.", ephemeral=True)
        await quiz_cog.post(interaction.channel)

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
