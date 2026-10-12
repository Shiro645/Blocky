from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import moderation, restrictions
from game.errors import GameError
from game.moderation import format_duration
from utils.checks import is_staff, staff_only
from utils.ui import dm, join_lines

DURATION_HELP = "e.g. 30m, 2h, 3d, 1w, or perm (until you lift it)"
Reason = app_commands.Range[str, 1, 400]


def until_text(block: dict) -> str:
    return "until lifted" if block["until"] is None else f"until <t:{block['until']}:f> (<t:{block['until']}:R>)"


class StaffBlockyCog(commands.Cog):
    """Staff: block a player from Blocky (commands, buttons, menus) for a while or until lifted."""

    group = app_commands.Group(name="blocky", description="STAFF: Block players who abuse Blocky.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def log(self, title: str, member: discord.abc.User, staff: discord.abc.User, details: str,
                  reason: str | None, color: discord.Color) -> None:
        embed = discord.Embed(title=title, description=details, color=color)
        embed.add_field(name="Member", value=f"{member.mention} (`{member}`)", inline=True)
        embed.add_field(name="By", value=f"{staff.mention} (`{staff}`)", inline=True)
        embed.add_field(name="Reason", value=reason or "—", inline=False)
        await self.bot.announcer.send(embed=embed, channel="staff_log")

    @group.command(name="ban", description="STAFF: Block a player from Blocky's commands and buttons.")
    @app_commands.describe(member="Who to block", duration=DURATION_HELP, reason="Why (sent to the player)")
    @staff_only()
    async def ban(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: Reason):
        if member.bot or member.id == interaction.user.id:
            raise GameError("Pick another player.")
        if is_staff(member):
            raise GameError("You can't block a staff member.")
        seconds = moderation.parse_duration(duration)
        block = await self.bot.db.run(restrictions.ban, member.id, seconds, reason, interaction.user.id)
        self.bot.blocked[member.id] = block  # type: ignore[attr-defined]
        length = format_duration(seconds)
        again = " (replaces their previous block)" if block["before"] else ""
        await interaction.response.send_message(
            f"⛔ {member.mention} is blocked from Blocky {until_text(block)}{again}.", ephemeral=True,
        )
        server = f" on **{interaction.guild.name}**" if interaction.guild else ""
        delivered = await dm(member, f"⛔ You are blocked from Blocky{server} ({length}): you can't use its commands "
                                     f"and buttons {until_text(block)}. You keep everything you own.\nReason: {reason}")
        await self.log(f"⛔ Blocked from Blocky ({length})", member, interaction.user,
                       f"{until_text(block).capitalize()}." + ("" if delivered else "\nCould not DM the player."),
                       reason, discord.Color.dark_red())

    @group.command(name="unban", description="STAFF: Let a blocked player use Blocky again.")
    @app_commands.describe(member="Who to unblock", reason="Why (sent to the player)")
    @staff_only()
    async def unban(self, interaction: discord.Interaction, member: discord.Member, reason: Reason | None = None):
        await self.bot.db.run(restrictions.unban, member.id)
        self.bot.blocked.pop(member.id, None)  # type: ignore[attr-defined]
        await interaction.response.send_message(f"✅ {member.mention} can use Blocky again.", ephemeral=True)
        server = f" on **{interaction.guild.name}**" if interaction.guild else ""
        await dm(member, f"✅ You can use Blocky again{server}." + (f"\nReason: {reason}" if reason else ""))
        await self.log("✅ Unblocked from Blocky", member, interaction.user, "The block was lifted.", reason,
                       discord.Color.green())

    @group.command(name="list", description="STAFF: Who is blocked from Blocky, and until when.")
    @staff_only()
    async def list_blocked(self, interaction: discord.Interaction):
        blocks = await self.bot.db.run(restrictions.active)
        self.bot.blocked = blocks  # type: ignore[attr-defined]
        lines = [
            f"<@{b['user_id']}> — {until_text(b)} · by <@{b['by_id']}>" + (f"\n└ {b['reason']}" if b["reason"] else "")
            for b in blocks.values()
        ]
        embed = discord.Embed(title="⛔ Blocked from Blocky", description=join_lines(lines, 4000, "Nobody is blocked."),
                              color=discord.Color.dark_red())
        await interaction.response.send_message(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot):
    await bot.add_cog(StaffBlockyCog(bot))
