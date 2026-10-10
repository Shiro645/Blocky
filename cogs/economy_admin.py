from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import players, shop
from game.catalog import BLOCK_TYPES, GEAR_ITEMS, MATERIALS
from utils.checks import staff_only
from utils.ui import em, gear_icon, item_label

BLOCK_CHOICES = [app_commands.Choice(name=b, value=b) for b in BLOCK_TYPES]
GEAR_CHOICES = [app_commands.Choice(name=g, value=g) for g in GEAR_ITEMS]
MATERIAL_CHOICES = [app_commands.Choice(name=m, value=m) for m in MATERIALS]
RESOURCE_CHOICES = [app_commands.Choice(name="stick", value="stick:none")] + [
    app_commands.Choice(name=f"{m} ingot", value=f"ingot:{m}") for m in MATERIALS
] + [app_commands.Choice(name="lapis lazuli", value="lapis:none")]

Amount = app_commands.Range[int, 1, 1_000_000]


class EconomyAdminCog(commands.Cog):
    """Staff commands to adjust the economy."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _done(self, interaction: discord.Interaction, text: str) -> None:
        await interaction.response.send_message(f"✅ {text}", ephemeral=True)

    # ---------- economy ----------
    @app_commands.command(name="add_block", description="STAFF: Add blocks to a member.")
    @app_commands.describe(member="Who gets the blocks", block_type="Which block", amount="How many blocks")
    @app_commands.choices(block_type=BLOCK_CHOICES)
    @staff_only()
    async def add_block(self, interaction: discord.Interaction, member: discord.Member, block_type: str, amount: Amount):
        def run(ctx):
            players.add_blocks(ctx, member.id, block_type, amount)
            return players.get_blocks(ctx, member.id)[block_type]

        total = await self.bot.db.run(run)
        await self._done(interaction, f"Added **{amount} {block_type}** to {member.mention} (now {total}).")

    @app_commands.command(name="add_emerald", description="STAFF: Give emeralds to a member.")
    @app_commands.describe(member="Who gets the emeralds", amount="How many emeralds")
    @staff_only()
    async def add_emerald(self, interaction: discord.Interaction, member: discord.Member, amount: Amount):
        def run(ctx):
            players.give_emeralds(ctx, member.id, amount)
            return players.get_emeralds(ctx, member.id)

        balance = await self.bot.db.run(run)
        await self._done(interaction, f"Added **{em(amount)}** to {member.mention}. Balance: **{em(balance)}**.")

    @app_commands.command(name="remove_emerald", description="STAFF: Remove emeralds from a member.")
    @app_commands.describe(member="Whose emeralds to remove", amount="How many emeralds")
    @staff_only()
    async def remove_emerald(self, interaction: discord.Interaction, member: discord.Member, amount: Amount):
        balance = await self.bot.db.run(players.remove_emeralds_clamped, member.id, amount)
        await self._done(interaction, f"Removed up to **{em(amount)}** from {member.mention}. Balance: **{em(balance)}**.")

    @app_commands.command(name="add_item", description="STAFF: Give sticks, ingots or lapis to a member.")
    @app_commands.describe(member="Who gets the items", resource="Sticks, an ingot or lapis lazuli", amount="How many")
    @app_commands.choices(resource=RESOURCE_CHOICES)
    @staff_only()
    async def add_item(self, interaction: discord.Interaction, member: discord.Member, resource: str, amount: Amount):
        item, material = resource.split(":")
        total = await self.bot.db.run(players.add_item, member.id, item, material, amount)
        await self._done(interaction, f"Gave **{item_label(item, material, amount)}** to {member.mention} (now {total}).")

    @app_commands.command(name="add_gear", description="STAFF: Give a piece of gear to a member.")
    @app_commands.describe(member="Who gets the piece", gear="Which piece", material="Which material")
    @app_commands.choices(gear=GEAR_CHOICES, material=MATERIAL_CHOICES)
    @staff_only()
    async def add_gear(self, interaction: discord.Interaction, member: discord.Member, gear: str, material: str):
        await self.bot.db.run(shop.create_gear, member.id, gear, material)
        await self._done(interaction, f"Gave {gear_icon(gear, material)} **{material} {gear}** to {member.mention}.")

    @app_commands.command(name="remove_gear", description="STAFF: Remove pieces of gear from a member.")
    @app_commands.describe(
        member="Whose gear to remove",
        gear="Which piece",
        material="Which material",
        count="How many pieces (unequipped ones first)",
    )
    @app_commands.choices(gear=GEAR_CHOICES, material=MATERIAL_CHOICES)
    @staff_only()
    async def remove_gear(
        self, interaction: discord.Interaction, member: discord.Member, gear: str, material: str,
        count: app_commands.Range[int, 1, 100] = 1,
    ):
        removed = await self.bot.db.run(shop.remove_gear, member.id, gear, material, count)
        await self._done(interaction, f"Removed **{removed}** {material} {gear} from {member.mention}.")

    # ---------- XP / talents ----------
    @app_commands.command(name="xp_add", description="STAFF: Give XP to a member.")
    @app_commands.describe(member="Who gets the XP", amount="How much XP")
    @staff_only()
    async def xp_add(self, interaction: discord.Interaction, member: discord.Member, amount: Amount):
        p = await self.bot.db.run(players.add_xp, member.id, amount)
        await self._done(interaction, f"{member.mention} is now level **{p['level']}** ({p['xp']} XP).")

    @app_commands.command(name="xp_set", description="STAFF: Set a member's XP inside their level.")
    @app_commands.describe(member="Whose XP to set", xp="XP inside the current level")
    @staff_only()
    async def xp_set(self, interaction: discord.Interaction, member: discord.Member, xp: app_commands.Range[int, 0]):
        p = await self.bot.db.run(players.set_xp, member.id, xp)
        await self._done(interaction, f"{member.mention} is now level **{p['level']}** ({p['xp']} XP).")

    @app_commands.command(name="level_set", description="STAFF: Set a member's level (talent points are recomputed).")
    @app_commands.describe(member="Whose level to set", level="The new level")
    @staff_only()
    async def level_set(self, interaction: discord.Interaction, member: discord.Member, level: app_commands.Range[int, 1, 10_000]):
        p = await self.bot.db.run(players.set_level, member.id, level)
        await self._done(
            interaction,
            f"{member.mention} is now level **{p['level']}** with **{p['talent_points']}** unspent talent point(s).",
        )

    @app_commands.command(name="talent_add", description="STAFF: Add (or remove, if negative) talent points.")
    @app_commands.describe(member="Who gets the points", points="Points to add (negative to remove some)")
    @staff_only()
    async def talent_add(self, interaction: discord.Interaction, member: discord.Member, points: int):
        p = await self.bot.db.run(players.add_talent_points, member.id, points)
        await self._done(interaction, f"{member.mention} has **{p['talent_points']}** unspent talent point(s).")

    @app_commands.command(name="talent_reset", description="STAFF: Reset a member's talents (points are refunded).")
    @app_commands.describe(member="Whose talents to reset")
    @staff_only()
    async def talent_reset(self, interaction: discord.Interaction, member: discord.Member):
        p = await self.bot.db.run(players.reset_talents, member.id)
        await self._done(interaction, f"{member.mention}'s talents were reset. Unspent points: **{p['talent_points']}**.")

    @app_commands.command(name="sync_level_roles", description="STAFF: Give every member the level role matching their level.")
    @staff_only()
    async def sync_level_roles(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        levels = await self.bot.db.run(lambda ctx: [(r["user_id"], r["level"]) for r in ctx.all("SELECT user_id, level FROM users;")])
        for user_id, level in levels:
            await self.bot.announcer.sync_level_role(user_id, level)
        await interaction.followup.send(f"✅ Level roles checked for **{len(levels)}** player(s).", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyAdminCog(bot))
