from __future__ import annotations

import asyncio
import re

import discord
from discord import app_commands
from discord.ext import commands

from game.errors import GameError
from utils.checks import staff_only
from utils.mc_commands import clean_output
from utils.minecraft_rcon import RconError, rcon_command
from utils.mojang import fetch_uuid


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")


async def run_rcon(command: str) -> str:
    """Run a console command; a readable error if the server can't be reached or isn't configured."""
    try:
        return clean_output(await rcon_command(command), limit=1800)
    except KeyError as e:
        raise GameError(f"The Minecraft settings are incomplete in config.json (missing {e}).")
    except (RconError, OSError, asyncio.TimeoutError) as e:
        raise GameError(f"Couldn't reach the Minecraft server console: {e}")


class MinecraftWhitelistCog(commands.Cog):
    whitelist = app_commands.Group(name="whitelist", description="STAFF: The Minecraft server whitelist.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @whitelist.command(name="add", description="STAFF: Add a player to the Minecraft whitelist.")
    @app_commands.describe(username="Minecraft Java username")
    @staff_only()
    async def add(self, interaction: discord.Interaction, username: str):
        if not USERNAME_RE.match(username):
            raise GameError("Invalid username (3-16 letters, numbers or _).")
        await interaction.response.defer(ephemeral=True)
        if await fetch_uuid(username) is None:
            raise GameError(f"**{username}** is not a Minecraft Java account (Mojang API).")
        resp = await run_rcon(f"whitelist add {username}")
        await interaction.followup.send(f"✅ **{username}** added to the whitelist.\n```{resp}```", ephemeral=True)

    @whitelist.command(name="remove", description="STAFF: Remove a player from the Minecraft whitelist.")
    @app_commands.describe(username="Minecraft Java username")
    @staff_only()
    async def remove(self, interaction: discord.Interaction, username: str):
        if not USERNAME_RE.match(username):
            raise GameError("Invalid username (3-16 letters, numbers or _).")
        await interaction.response.defer(ephemeral=True)
        resp = await run_rcon(f"whitelist remove {username}")
        await interaction.followup.send(f"✅ **{username}** removed from the whitelist.\n```{resp}```", ephemeral=True)

    @whitelist.command(name="list", description="STAFF: Show the current Minecraft whitelist.")
    @staff_only()
    async def list_players(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        resp = await run_rcon("whitelist list")
        await interaction.followup.send(f"📋 Whitelist:\n```{resp}```", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftWhitelistCog(bot))