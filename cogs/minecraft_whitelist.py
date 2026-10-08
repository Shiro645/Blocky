from __future__ import annotations

import aiohttp
import re

import discord
from discord import app_commands
from discord.ext import commands

from utils.config import load_config
from utils.minecraft_rcon import rcon_command


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")


def staff_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False

        cfg = load_config()
        staff_role_id = int(cfg.get("staff", {}).get("role_id", 0) or 0)

        member = interaction.user
        if not isinstance(member, discord.Member):
            member = await interaction.guild.fetch_member(interaction.user.id)

        if member.guild_permissions.manage_guild:
            return True

        role = interaction.guild.get_role(staff_role_id)
        return role is not None and role in member.roles
    return app_commands.check(predicate)


async def fetch_uuid(username: str) -> str | None:
    url = f"https://api.mojang.com/users/profiles/minecraft/{username}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            raw_uuid = data["id"]
            return (
                f"{raw_uuid[0:8]}-"
                f"{raw_uuid[8:12]}-"
                f"{raw_uuid[12:16]}-"
                f"{raw_uuid[16:20]}-"
                f"{raw_uuid[20:]}"
            )


class MinecraftWhitelistCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="add_whitelist", description="Add a player to the Minecraft whitelist.")
    @staff_only()
    async def add_whitelist(self, interaction: discord.Interaction, username: str):
        if not USERNAME_RE.match(username):
            return await interaction.response.send_message("❌ Invalid username.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        uuid = await fetch_uuid(username)
        if uuid is None:
            return await interaction.followup.send("❌ Username not found (Mojang API).", ephemeral=True)

        try:
            resp = rcon_command(f"whitelist add {username}")
            await interaction.followup.send(
                f"✅ **{username}** added to whitelist.\n```{resp}```",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to add **{username}** to whitelist.\n```{e}```",
                ephemeral=True
            )

    @app_commands.command(name="remove_whitelist", description="Remove a player from the Minecraft whitelist.")
    @staff_only()
    async def remove_whitelist(self, interaction: discord.Interaction, username: str):
        if not USERNAME_RE.match(username):
            return await interaction.response.send_message("❌ Invalid username.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        try:
            resp = rcon_command(f"whitelist remove {username}")
            await interaction.followup.send(
                f"✅ **{username}** removed from whitelist.\n```{resp}```",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to remove **{username}** from whitelist.\n```{e}```",
                ephemeral=True
            )

    @app_commands.command(name="check_whitelist", description="Check if a player is whitelisted.")
    @staff_only()
    async def check_whitelist(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            resp = rcon_command("whitelist list")
            await interaction.followup.send(
                f"📋 Whitelist status:\n```{resp}```",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to check whitelist.\n```{e}```",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftWhitelistCog(bot))