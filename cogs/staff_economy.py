from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import assets, players
from game.errors import GameError
from utils.autocomplete import owned_asset_choices
from utils.checks import staff_only
from utils.ui import ConfirmView, asset_icon, dm

Amount = app_commands.Range[int, 1, 1_000_000]
Reason = app_commands.Range[str, 1, 300]


def what(key: str, amount: int) -> str:
    """'💎 **3 × diamond ingot**'"""
    return f"{asset_icon(key)} **{assets.describe(key, amount)}**".strip()


class StaffEconomyCog(commands.Cog):
    """Staff: give and take anything, change a member's XP, level and talents. Members get a DM."""

    player = app_commands.Group(name="player", description="STAFF: Change a member's XP, level and talents.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- helpers ----------
    async def answer(
        self, interaction: discord.Interaction, text: str, member: discord.abc.User, news: str,
        reason: str | None = None, *, edit: bool = False,
    ) -> None:
        """Answer the staff member first (Discord gives 3 seconds), then DM the member the `news`."""
        if edit:
            await interaction.response.edit_message(content=text, view=None)
        else:
            await interaction.response.send_message(text, ephemeral=True)
        server = f"**{interaction.guild.name}** · " if interaction.guild else ""
        if not await dm(member, f"{server}{news}." + (f"\nReason: {reason}" if reason else "")):
            await interaction.edit_original_response(content=text + "\n*(Couldn't DM them: their DMs are closed.)*")

    async def log(self, title: str, member: discord.abc.User, staff: discord.abc.User, details: str, reason: str | None) -> None:
        embed = discord.Embed(title=title, description=details, color=discord.Color.blurple())
        embed.add_field(name="Member", value=f"{member.mention} (`{member}`)", inline=True)
        embed.add_field(name="By", value=f"{staff.mention} (`{staff}`)", inline=True)
        embed.add_field(name="Reason", value=reason or "—", inline=False)
        await self.bot.announcer.send(embed=embed, channel="staff_log")

    # ---------- autocomplete ----------
    async def give_autocomplete(self, interaction: discord.Interaction, current: str):
        text = current.strip().lower()
        choices = []
        try:  # a full key typed by hand, e.g. an enchanted piece "gear:diamond:sword:sharpness3"
            assets.parse(text)
            choices.append(app_commands.Choice(name=assets.describe(text)[:100], value=text))
        except GameError:
            pass
        for key in assets.catalog():
            name = assets.describe(key)
            if key != text and (text in name.lower() or text in key):
                choices.append(app_commands.Choice(name=name, value=key))
        return choices[:25]

    async def take_autocomplete(self, interaction: discord.Interaction, current: str):
        member = getattr(interaction.namespace, "member", None)
        if member is None:  # pick the member first: the suggestions are what they own
            return []
        return await owned_asset_choices(self.bot, member.id, current)

    # ---------- give / take ----------
    @app_commands.command(name="give", description="STAFF: Give anything to a member (emeralds, blocks, items, books, potions, gear).")
    @app_commands.describe(
        member="Who gets it",
        item="What to give (start typing; for an enchanted piece type e.g. gear:diamond:sword:sharpness3)",
        amount="How many (gear: 50 at most)",
        reason="Why (sent to the member and logged)",
    )
    @app_commands.autocomplete(item=give_autocomplete)
    @staff_only()
    async def give(
        self, interaction: discord.Interaction, member: discord.Member, item: str,
        amount: Amount = 1, reason: Reason | None = None,
    ):
        key = item.strip().lower()
        assets.parse(key)  # a readable error for an unknown item
        total = await self.bot.db.run(assets.staff_give, member.id, key, amount)
        await self.answer(
            interaction, f"✅ Gave {what(key, amount)} to {member.mention} (they have **{total:,}** now).",
            member, f"🎁 The staff gave you {what(key, amount)}", reason,
        )
        await self.log("🎁 Staff gift", member, interaction.user, f"Gave {what(key, amount)} (now {total:,})", reason)

    @app_commands.command(name="take", description="STAFF: Remove anything a member owns (asks for confirmation).")
    @app_commands.describe(
        member="Whose inventory",
        item="What to remove (the suggestions are what they own)",
        amount="How many (never more than they have)",
        reason="Why (sent to the member and logged)",
    )
    @app_commands.autocomplete(item=take_autocomplete)
    @staff_only()
    async def take(
        self, interaction: discord.Interaction, member: discord.Member, item: str,
        amount: Amount = 1, reason: Reason | None = None,
    ):
        key = item.strip().lower()
        have = await self.bot.db.run(assets.amount_of, member.id, key)
        if have <= 0:
            raise GameError(f"{member.mention} has no **{assets.describe(key)}**.")
        count = min(amount, have)
        extra = f" You asked for {amount:,}, they only have {have:,}." if amount > have else ""

        async def do(confirm: discord.Interaction) -> None:
            removed, left = await self.bot.db.run(assets.staff_take, member.id, key, count)
            await self.answer(
                confirm, f"✅ Removed {what(key, removed)} from {member.mention} (**{left:,}** left).",
                member, f"📦 The staff removed {what(key, removed)} from your inventory", reason, edit=True,
            )
            await self.log("📦 Staff removal", member, interaction.user, f"Removed {what(key, removed)} ({left:,} left)", reason)

        await interaction.response.send_message(
            f"Remove {what(key, count)} from {member.mention}? They have **{have:,}**.{extra}",
            view=ConfirmView(interaction.user.id, "Remove", do), ephemeral=True,
        )

    # ---------- /player ----------
    @player.command(name="xp_add", description="STAFF: Give XP to a member (levels and talent points follow).")
    @app_commands.describe(member="Who gets the XP", amount="How much XP")
    @staff_only()
    async def xp_add(self, interaction: discord.Interaction, member: discord.Member, amount: Amount):
        p = await self.bot.db.run(players.add_xp, member.id, amount)
        await self.answer(
            interaction, f"✅ {member.mention} is now level **{p['level']}** ({p['xp']} XP).",
            member, f"✨ The staff gave you **{amount:,} XP** (you're level **{p['level']}**)",
        )

    @player.command(name="xp_set", description="STAFF: Set a member's XP inside their current level.")
    @app_commands.describe(member="Whose XP to set", xp="XP inside the current level")
    @staff_only()
    async def xp_set(self, interaction: discord.Interaction, member: discord.Member, xp: app_commands.Range[int, 0]):
        p = await self.bot.db.run(players.set_xp, member.id, xp)
        await self.answer(
            interaction, f"✅ {member.mention} is now level **{p['level']}** ({p['xp']} XP).",
            member, f"✨ The staff set your XP to **{p['xp']:,}** (level **{p['level']}**)",
        )

    @player.command(name="level", description="STAFF: Set a member's level (unspent talent points are recomputed).")
    @app_commands.describe(member="Whose level to set", level="The new level")
    @staff_only()
    async def level(self, interaction: discord.Interaction, member: discord.Member, level: app_commands.Range[int, 1, 10_000]):
        p = await self.bot.db.run(players.set_level, member.id, level)
        await self.answer(
            interaction,
            f"✅ {member.mention} is now level **{p['level']}** with **{p['talent_points']}** unspent talent point(s).",
            member, f"⭐ The staff set your level to **{p['level']}**",
        )
        await self.bot.announcer.sync_level_role(member.id, p["level"])

    @player.command(name="talents_add", description="STAFF: Add talent points (a negative number removes some).")
    @app_commands.describe(member="Who gets the points", points="Points to add (negative to remove some)")
    @staff_only()
    async def talents_add(self, interaction: discord.Interaction, member: discord.Member, points: app_commands.Range[int, -1000, 1000]):
        if points == 0:
            raise GameError("0 points: nothing to change.")
        p = await self.bot.db.run(players.add_talent_points, member.id, points)
        change = f"gave you **{points}**" if points > 0 else f"removed **{-points}** of your"
        await self.answer(
            interaction, f"✅ {member.mention} has **{p['talent_points']}** unspent talent point(s).",
            member, f"🌟 The staff {change} talent point(s) (unspent: **{p['talent_points']}**)",
        )

    @player.command(name="talents_reset", description="STAFF: Reset a member's talents (every spent point is refunded).")
    @app_commands.describe(member="Whose talents to reset")
    @staff_only()
    async def talents_reset(self, interaction: discord.Interaction, member: discord.Member):
        p = await self.bot.db.run(players.reset_talents, member.id)
        await self.answer(
            interaction, f"✅ {member.mention}'s talents were reset. Unspent points: **{p['talent_points']}**.",
            member, f"🌟 The staff reset your talents: you have **{p['talent_points']}** points to spend again with /talent_buy",
        )

    @player.command(name="sync_roles", description="STAFF: Give every member the level role matching their level.")
    @staff_only()
    async def sync_roles(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        levels = await self.bot.db.run(lambda ctx: [(r["user_id"], r["level"]) for r in ctx.all("SELECT user_id, level FROM users;")])
        for user_id, level in levels:
            await self.bot.announcer.sync_level_role(user_id, level)
        await interaction.followup.send(f"✅ Level roles checked for **{len(levels)}** player(s).", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(StaffEconomyCog(bot))
