from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.config import load_config
from database import (
    init_db,
    ensure_user,
    add_blocks,
    add_emeralds,
    add_item,
    add_gear,
    BLOCK_TYPES,
)

from utils.config import load_emojis

EMOJI = load_emojis()

MATERIALS = ("gold", "iron", "diamond", "netherite")
GEAR = ("sword", "pickaxe", "axe", "shovel", "hoe", "helmet", "chestplate", "leggings", "boots")


def admin_only():
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


def _mat_emoji(material: str) -> str:
    return EMOJI.get(material, "")


class EconomyAdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()

    @app_commands.command(name="add_block", description="ADMIN: Add blocks to a user's inventory.")
    @admin_only()
    async def add_block(self, interaction: discord.Interaction, member: discord.Member, block_type: str, amount: int):
        block_type = block_type.lower()
        if block_type not in BLOCK_TYPES:
            return await interaction.response.send_message(
                f"❌ Invalid block type. Allowed: {', '.join(BLOCK_TYPES)}",
                ephemeral=True,
            )
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount must be > 0.", ephemeral=True)

        ensure_user(member.id)
        new_amt = add_blocks(member.id, block_type, amount)
        await interaction.response.send_message(
            f"✅ Added **{amount} {block_type}** to {member.mention}. New amount: **{new_amt}**",
            ephemeral=True,
        )

    @app_commands.command(name="add_emerald", description="ADMIN: Add emeralds to a user.")
    @admin_only()
    async def add_emerald(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount must be > 0.", ephemeral=True)

        ensure_user(member.id)
        new_balance = add_emeralds(member.id, amount)
        await interaction.response.send_message(
            f"✅ Added **{amount} {EMOJI['emerald']}** to {member.mention}. New balance: **{new_balance} {EMOJI['emerald']}**",
            ephemeral=True,
        )

    @app_commands.command(name="add_item", description="ADMIN: Add resources to YOUR inventory (sticks/ingots).")
    @admin_only()
    async def add_item_simple(self, interaction: discord.Interaction, item: str, amount: int):
        item = item.lower().strip()
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount must be > 0.", ephemeral=True)

        ensure_user(interaction.user.id)

        if item in ("stick", "sticks"):
            new_amt = add_item(interaction.user.id, "stick", "none", amount)
            return await interaction.response.send_message(
                f"✅ Added **{amount} {EMOJI['stick']} sticks**. New amount: **{new_amt}**",
                ephemeral=True,
            )

        mat = item[:-6] if item.endswith("_ingot") else item
        if mat in MATERIALS:
            new_amt = add_item(interaction.user.id, "ingot", mat, amount)
            return await interaction.response.send_message(
                f"✅ Added {_mat_emoji(mat)} **{amount} {mat} ingot(s)**. New amount: **{new_amt}**",
                ephemeral=True,
            )

        return await interaction.response.send_message(
            "❌ Invalid item. Use: stick | gold | iron | diamond | netherite (optionally *_ingot).",
            ephemeral=True,
        )

    @app_commands.command(name="add_gear", description="ADMIN: Add ONE gear piece to YOUR gear inventory.")
    @admin_only()
    async def add_gear_cmd(self, interaction: discord.Interaction, gear: str, material: str):
        gear = gear.lower().strip()
        material = material.lower().strip()

        if gear not in GEAR:
            return await interaction.response.send_message(
                f"❌ Invalid gear. Allowed: {', '.join(GEAR)}",
                ephemeral=True,
            )
        if material not in MATERIALS:
            return await interaction.response.send_message(
                f"❌ Invalid material. Allowed: {', '.join(MATERIALS)}",
                ephemeral=True,
            )

        ensure_user(interaction.user.id)
        add_gear(interaction.user.id, gear, material)
        await interaction.response.send_message(
            f"✅ Added {_mat_emoji(material)} **{material} {gear}** to your gear inventory.",
            ephemeral=True,
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyAdminCog(bot))
