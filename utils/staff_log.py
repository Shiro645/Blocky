"""Every staff command leaves a trace in the staff channel."""
from __future__ import annotations

import discord

# Commands that already write a detailed log entry themselves, or that change nothing.
SELF_LOGGED = {
    "config", "mc", "team_remove", "event tournament", "give", "take",
    "warn", "unwarn", "clearwarns", "mute", "unmute", "kick", "ban", "unban", "clear", "lock", "unlock", "slowmode",
}
READ_ONLY = {"history", "whitelist list"}


def format_value(value: object) -> str:
    if isinstance(value, (discord.Member, discord.User)):
        return f"{value.mention} (`{value}`)"
    if isinstance(value, (discord.Role, discord.abc.GuildChannel, discord.Thread)):
        return value.mention
    if isinstance(value, discord.Object):
        return f"`{value.id}`"
    text = str(value)
    return text if len(text) <= 200 else text[:199] + "…"


def describe(interaction: discord.Interaction) -> str:
    lines = [f"**{name}**: {format_value(value)}" for name, value in interaction.namespace]
    return "\n".join(lines) or "*no options*"


def wanted(name: str) -> bool:
    return name not in SELF_LOGGED and name not in READ_ONLY


def embed_for(interaction: discord.Interaction, name: str) -> discord.Embed:
    embed = discord.Embed(title=f"🛠️ /{name}", description=describe(interaction)[:4000], color=discord.Color.blurple())
    embed.add_field(name="By", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=False)
    if interaction.channel is not None:
        embed.add_field(name="In", value=getattr(interaction.channel, "mention", "DM"), inline=False)
    return embed
