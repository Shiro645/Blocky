from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from game import links
from game.errors import GameError
from utils.checks import is_staff, staff_only
from utils.minecraft_rcon import rcon_command
from utils.mojang import fetch_uuid
from utils.ui import report_error

log = logging.getLogger("link")


class LinkDecisionButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"blocky:link:(?P<action>approve|reject):(?P<user_id>\d+):(?P<name>[A-Za-z0-9_]{3,16})",
):
    """Approve / Reject buttons on the staff message. They survive restarts."""

    def __init__(self, action: str, user_id: int, name: str) -> None:
        approve = action == "approve"
        super().__init__(
            discord.ui.Button(
                label="Approve" if approve else "Reject",
                style=discord.ButtonStyle.success if approve else discord.ButtonStyle.danger,
                emoji="✅" if approve else "✖️",
                custom_id=f"blocky:link:{action}:{user_id}:{name}",
            )
        )
        self.action, self.user_id, self.name = action, user_id, name

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(match["action"], int(match["user_id"]), match["name"])

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: LinkCog | None = interaction.client.get_cog("LinkCog")  # type: ignore[assignment]
        if cog is None:
            return
        try:
            if not is_staff(interaction.user):
                raise GameError("Only staff can decide on link requests.")
            await cog.decide(interaction, self.action, self.user_id, self.name)
        except Exception as error:
            await report_error(interaction, error)


def decision_view(user_id: int, name: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(LinkDecisionButton("approve", user_id, name))
    view.add_item(LinkDecisionButton("reject", user_id, name))
    return view


class LinkCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(LinkDecisionButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(LinkDecisionButton)

    async def dm(self, user_id: int, text: str) -> None:
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            await user.send(text)
        except discord.HTTPException:
            pass

    @app_commands.command(name="link", description="Link your Minecraft account (gets you whitelisted once staff approves).")
    @app_commands.describe(username="Your Minecraft Java username")
    async def link(self, interaction: discord.Interaction, username: str):
        staff_channel = self.bot.announcer.channel("staff_log")
        if staff_channel is None:
            raise GameError("Account linking is not set up on this server (no staff channel configured).")
        if not links.USERNAME_RE.match(username):
            raise GameError("Invalid Minecraft username (3-16 letters, digits or _).")

        await interaction.response.defer(ephemeral=True, thinking=True)
        uuid = await fetch_uuid(username)
        if uuid is None:
            raise GameError(f"**{username}** is not a Minecraft Java account (Mojang API).")

        req = await self.bot.db.run(links.request_link, interaction.user.id, username)
        embed = discord.Embed(
            title="🔗 Link request",
            description=(
                f"{interaction.user.mention} (`{interaction.user}`) wants to link **{req['mc_username']}**.\n"
                f"UUID: `{uuid}`\n\nApproving adds the account to the whitelist."
            ),
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{uuid}")
        try:
            await staff_channel.send(embed=embed, view=decision_view(interaction.user.id, req["mc_username"]))
        except discord.Forbidden:
            # Nobody would see the request: cancel it so the member can retry later.
            await self.bot.db.run(links.unlink, interaction.user.id)
            log.error("Missing access to the staff channel %s", getattr(staff_channel, "id", "?"))
            raise GameError(
                "The bot can't post in the staff channel. Ask an admin to give it "
                "View Channel, Send Messages and Embed Links there, then try again."
            )
        await interaction.followup.send(
            f"✅ Request sent for **{req['mc_username']}**. A staff member will review it soon; you'll get a DM.",
            ephemeral=True,
        )

    async def decide(self, interaction: discord.Interaction, action: str, user_id: int, name: str) -> None:
        await self.bot.db.run(links.check_pending, user_id, name)
        if action == "approve":
            await interaction.response.defer()
            try:
                resp = await rcon_command(f"whitelist add {name}")
            except Exception as e:
                raise GameError(f"Could not reach the Minecraft server, nothing was changed.\n```{e}```")
            await self.bot.db.run(links.approve, user_id, interaction.user.id)
            status = f"✅ Approved by {interaction.user.mention} — `{resp.strip() or 'whitelisted'}`"
            color = discord.Color.green()
            await self.dm(user_id, f"✅ Your Minecraft account **{name}** is linked and whitelisted. See you in game!")
        else:
            await self.bot.db.run(links.reject, user_id, interaction.user.id)
            status = f"✖️ Rejected by {interaction.user.mention}"
            color = discord.Color.red()
            await self.dm(user_id, f"✖️ Your link request for **{name}** was rejected. Contact the staff if this is a mistake.")

        embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else discord.Embed()
        embed.color = color
        embed.add_field(name="Decision", value=status, inline=False)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=None)
        else:
            await interaction.response.edit_message(embed=embed, view=None)

    @app_commands.command(name="link_status", description="Show the Minecraft account linked to you.")
    async def link_status(self, interaction: discord.Interaction):
        link = await self.bot.db.run(links.get_link, interaction.user.id)
        if link is None:
            text = "You have no linked Minecraft account. Use `/link <username>`."
        elif link["status"] == "pending":
            text = f"⏳ Your request for **{link['mc_username']}** is waiting for staff approval."
        else:
            text = f"🔗 Linked to **{link['mc_username']}** (whitelisted)."
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="unlink", description="STAFF: Remove a member's Minecraft link (and whitelist entry).")
    @app_commands.describe(member="Whose link to remove")
    @staff_only()
    async def unlink(self, interaction: discord.Interaction, member: discord.User):
        await interaction.response.defer(ephemeral=True)
        link = await self.bot.db.run(links.unlink, member.id)
        text = f"✅ {member.mention} is no longer linked to **{link['mc_username']}**."
        if link["status"] == "approved":
            try:
                await rcon_command(f"whitelist remove {link['mc_username']}")
                text += " Removed from the whitelist."
            except Exception as e:
                text += f"\n⚠️ Could not remove them from the whitelist, do it manually.\n```{e}```"
        await interaction.followup.send(text, ephemeral=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """A member leaving the server loses their whitelist spot."""
        if member.guild != self.bot.main_guild:
            return
        try:
            link = await self.bot.db.run(links.unlink, member.id)
        except GameError:
            return
        if link["status"] == "approved":
            try:
                await rcon_command(f"whitelist remove {link['mc_username']}")
            except Exception:
                log.exception("Could not remove %s from the whitelist", link["mc_username"])
        await self.bot.announcer.send(
            f"👋 {member} left the server: Minecraft account **{link['mc_username']}** unlinked"
            + (" and removed from the whitelist." if link["status"] == "approved" else "."),
            channel="staff_log",
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(LinkCog(bot))
