from __future__ import annotations

import discord
from discord import app_commands

from game.errors import GameError
from utils.config import channel_ids, staff_role_id


def is_staff(member: discord.abc.User) -> bool:
    """Members with the staff role (config staff.role_id). Only when no staff role is set (or it was
    deleted), the administrators, so the server is never locked out of the staff commands."""
    if not isinstance(member, discord.Member):
        return False
    role_id = staff_role_id()
    if role_id and member.guild.get_role(role_id) is not None:
        return any(r.id == role_id for r in member.roles)
    return member.guild_permissions.administrator


def staff_only():
    """The staff role (see is_staff)."""

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
    """A command with the staff_only() check, or a group made only of such commands."""
    if isinstance(command, app_commands.Group):
        subcommands = command.commands
        return bool(subcommands) and all(is_staff_command(c) for c in subcommands)
    return any(getattr(check, "blocky_staff", False) for check in getattr(command, "checks", []))


def check_game_channel(interaction: discord.Interaction) -> None:
    """Mini-games only work in the game channels (config.json channels.games), or anywhere when there are none.

    Guide channels count as game channels, so new players can try the games the guide talks about."""
    allowed = channel_ids("games")
    channel = interaction.channel
    if not allowed or channel is None:
        return
    if channel.id in allowed or getattr(channel, "parent_id", None) in allowed:
        return
    if channel.id in getattr(interaction.client, "guide_channels", {}):  # a player's guide channel: try things there
        return
    raise GameError("Games are played in " + ", ".join(f"<#{c}>" for c in sorted(allowed)) + ".")
