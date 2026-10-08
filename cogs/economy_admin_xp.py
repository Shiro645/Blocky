from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from database import (
    init_db,
    ensure_user,
    add_xp,
    get_progress,
    set_xp_level,
    add_talent_points,
    reset_talents,
)

from utils.config import load_emojis

XP = load_emojis()["xp"]

class EconomyAdminXPCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        init_db()

    def is_admin(self, interaction: discord.Interaction):
        return interaction.user.guild_permissions.manage_guild

    @app_commands.command(name="xp_add")
    async def xp_add(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if not self.is_admin(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        ensure_user(member.id)
        before = get_progress(member.id)
        after = add_xp(member.id, amount)

        await interaction.response.send_message(
            f"{member.mention} XP: {before['xp']} → {after['xp']} {XP}",
            ephemeral=True
        )

    @app_commands.command(name="xp_set")
    async def xp_set(self, interaction: discord.Interaction, member: discord.Member, xp: int):
        if not self.is_admin(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        after = set_xp_level(member.id, xp=xp)
        await interaction.response.send_message(
            f"{member.mention} XP set to {after['xp']} {XP}",
            ephemeral=True
        )

    @app_commands.command(name="level_set")
    async def level_set(self, interaction: discord.Interaction, member: discord.Member, level: int):
        if not self.is_admin(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        after = set_xp_level(member.id, level=level)
        await interaction.response.send_message(
            f"{member.mention} level set to {after['level']}",
            ephemeral=True
        )

    @app_commands.command(name="talent_add")
    async def talent_add(self, interaction: discord.Interaction, member: discord.Member, points: int):
        if not self.is_admin(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        after = add_talent_points(member.id, points)
        await interaction.response.send_message(
            f"{member.mention} talent points: {after['talent_points']} {XP}",
            ephemeral=True
        )

    @app_commands.command(name="talent_reset")
    async def talent_reset(self, interaction: discord.Interaction, member: discord.Member):
        if not self.is_admin(interaction):
            return await interaction.response.send_message("No permission.", ephemeral=True)

        reset_talents(member.id)
        await interaction.response.send_message(
            f"{member.mention} talents reset.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(EconomyAdminXPCog(bot))
