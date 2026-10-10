from __future__ import annotations

import discord
from discord import app_commands

from utils.config import staff_role_id


def is_staff(member: discord.abc.User) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.manage_guild:
        return True
    role_id = staff_role_id()
    return any(r.id == role_id for r in member.roles)


def staff_only():
    """Staff role (config staff.role_id) or Manage Server permission."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        member = interaction.user
        if not isinstance(member, discord.Member):
            member = await interaction.guild.fetch_member(interaction.user.id)
        return is_staff(member)

    predicate.blocky_staff = True  # type: ignore[attr-defined]  (see is_staff_command)
    return app_commands.check(predicate)


def is_staff_command(command: object) -> bool:
    return any(getattr(check, "blocky_staff", False) for check in getattr(command, "checks", []))
