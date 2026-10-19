from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from game import dimensions, mining, players, settings
from game.catalog import DIMENSION_BLOCKS, DIMENSIONS, block_name
from utils.config import channel_ids, role_id
from utils.ui import block_icon, em, scrap_icon

log = logging.getLogger("dimensions")


def dimension_roles(guild: discord.Guild) -> dict[str, discord.Role]:
    """dimension -> its role (roles.dimension_<key>), for the roles that are set and exist (none for the
    overworld: everyone is there)."""
    out = {}
    for key in DIMENSIONS[1:]:
        rid = role_id(dimensions.role_key(key))
        role = guild.get_role(rid) if rid else None
        if rid and role is None:
            log.warning("roles.%s %s not found", dimensions.role_key(key), rid)
        if role is not None:
            out[key] = role
    return out


def income(dimension: str) -> float:
    """Emeralds a mining reward is worth on average in a dimension, without gear or talents."""
    total = 0.0
    for amount in range(1, 7):
        weights = mining.pile_weights(amount, 0, 0, 1.0, dimension)
        weight = sum(weights.values()) or 1
        total += amount * sum(w * players.block_value(b) for b, w in weights.items()) / weight
    return total / 6


class DimensionsCog(commands.Cog):
    """/dimensions: where a player can mine, and the roles of the dimensions they unlocked."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._role_lock = asyncio.Lock()

    # ---------- roles ----------
    async def sync_roles(self, user_id: int | None = None, old_role_id: int = 0) -> None:
        """Give each player the role of every dimension they unlocked, and take the others back.

        `user_id`: only this player. `old_role_id`: a role set before a /config change, taken back from everyone.
        """
        guild = getattr(self.bot, "main_guild", None)
        if guild is None:
            return
        async with self._role_lock:
            if user_id is None:
                levels = await self.bot.db.run(dimensions.all_levels)
            else:
                levels = {user_id: await self.bot.db.run(dimensions.level, user_id)}
            roles = dimension_roles(guild)
            changes: list[tuple[discord.Member, discord.Role, bool]] = []  # (member, role, give)
            old = guild.get_role(old_role_id) if old_role_id else None
            if old is not None and old not in roles.values():
                changes += [(m, old, False) for m in old.members if user_id in (None, m.id)]
            for key, role in roles.items():
                need = DIMENSIONS.index(key)
                changes += [(m, role, False) for m in role.members
                            if user_id in (None, m.id) and levels.get(m.id, 0) < need]
                for uid, lvl in levels.items():
                    member = guild.get_member(uid) if lvl >= need else None
                    if member is not None and role not in member.roles:
                        changes.append((member, role, True))
            for member, role, give in changes:
                try:
                    if give:
                        await member.add_roles(role, reason="Blocky: dimension unlocked")
                    else:
                        await member.remove_roles(role, reason="Blocky: dimension locked")
                except discord.HTTPException:
                    log.warning("Could not update the dimension role of %s (check Manage Roles and role order)", member)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.sync_roles()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = getattr(self.bot, "main_guild", None)
        if guild is not None and member.guild.id == guild.id:
            await self.sync_roles(member.id)

    @commands.Cog.listener()
    async def on_blocky_config_changed(self, key: str, before) -> None:
        if key.startswith("role_dimension_"):
            await self.sync_roles(old_role_id=int(before or 0))

    # ---------- commands ----------
    @app_commands.command(name="dimensions", description="The dimensions: where you mine, their blocks and your netherite.")
    async def dimensions_cmd(self, interaction: discord.Interaction):
        me = await self.bot.db.run(dimensions.overview, interaction.user.id)
        base = income("overworld") or 1
        embed = discord.Embed(
            title="🌍 Dimensions",
            description="Each dimension has its mining channels and its blocks, worth more than the one before. "
                        "Unlocking a dimension opens every one before it.",
            color=discord.Color.dark_purple(),
        )
        for i, key in enumerate(DIMENSIONS):
            state = "✅ unlocked" if me["level"] >= i else "🔒 locked"
            blocks = ", ".join(f"{block_icon(b)} {block_name(b)} {players.block_value(b)}" for b in DIMENSION_BLOCKS[key])
            chans = channel_ids(dimensions.channel_key(key))
            where = " ".join(f"<#{c}>" for c in sorted(chans)) if chans else (
                "every channel" if key == "overworld" else "no channel yet")
            value = income(key)
            embed.add_field(
                name=f"{dimensions.label(key)} — {state}",
                value=f"{blocks}\n≈ {em(round(value, 1))} a message (×{value / base:.2f}) · {where}",
                inline=False,
            )
        d = settings.get()["dimensions"]
        embed.add_field(
            name="🔥 Your netherite",
            value=(f"{scrap_icon()} **{me['scraps']}** scraps · **{me['ingots']}** ingot(s) · "
                   f"**{me['netherite_pieces']}** netherite piece(s)\n"
                   f"Mining in the Nether (or beyond) finds Ancient debris **{float(d['scrap_chance']) * 100:g}%** of "
                   f"the time. {d['scraps_per_ingot']} scraps + {d['gold_per_ingot']} gold ingots = a netherite ingot; "
                   "a diamond piece + 1 netherite ingot = the netherite piece (`/craft`). Netherite can't be bought, "
                   "sold or traded."),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(DimensionsCog(bot))
