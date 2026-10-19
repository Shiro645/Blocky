from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from game import prestige, settings
from game.catalog import DIMENSIONS, DIMENSION_NAMES
from utils.config import role_id
from utils.ui import BaseView, ConfirmView, join_lines, report_error

log = logging.getLogger("prestige")


def status_embed(st: dict) -> discord.Embed:
    n = st["prestige"]
    head = (f"You are **Prestige {prestige.roman(n)}** {prestige.stars(n)}: +{st['bonus']:.0%} mining XP and /sell "
            "for good.\n" if n else "")
    if st["next"] is None:
        return discord.Embed(title="🌟 Prestige", description=head + f"You reached the highest prestige "
                             f"(**{prestige.roman(st['max'])}**). Legendary!", color=discord.Color.gold())
    c = st["checks"]
    mark = lambda key: "✅" if c[key][0] >= c[key][1] else "❌"  # noqa: E731
    level, ach, dims = c["level"], c["achievements"], c["dimensions"]
    lines = [
        f"{mark('level')} Level **{level[1]}** (you: {level[0]})",
        f"{mark('achievements')} Every achievement ({ach[0]}/{ach[1]})",
        f"{mark('dimensions')} Every dimension, up to the {DIMENSION_NAMES[DIMENSIONS[-1]]} "
        f"(you: {DIMENSION_NAMES[DIMENSIONS[min(dims[0], len(DIMENSIONS) - 1)]]})",
        f"{mark('beacon')} The server's Beacon lit",
    ]
    bonus = float(settings.get()["prestige"]["bonus"])
    embed = discord.Embed(
        title=f"🌟 Prestige {prestige.roman(st['next'])}",
        description=head + "\n".join(lines),
        color=discord.Color.gold() if st["ready"] else discord.Color.dark_grey(),
    )
    if st["missing"]:
        embed.add_field(name="Achievements to get", value=join_lines([f"{a.icon} {a.name}" for a in st["missing"]]),
                        inline=False)
    lost = [prestige.PARTS[p] for p in st["resets"]]
    embed.add_field(name="You start over", value=join_lines([f"• {x}" for x in lost], empty="Nothing.")
                    + "\nYou keep your level, your team and the cosmetics you bought.", inline=False)
    embed.add_field(name="You get", value=f"+{bonus:.0%} mining XP and /sell for good (each prestige adds "
                    f"{bonus:.0%}), a ⭐ next to your name, the Prestige role and earned cosmetics (`/customize list`).",
                    inline=False)
    return embed


class PrestigeView(BaseView):
    def __init__(self, cog: "PrestigeCog", user_id: int):
        super().__init__(allowed_ids={user_id}, timeout=120)
        self.cog = cog

    @discord.ui.button(label="Become Prestige", emoji="🌟", style=discord.ButtonStyle.danger)
    async def go(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await self.cog.bot.db.run(prestige.status, interaction.user.id)
        lost = "\n".join(f"• {prestige.PARTS[p]}" for p in st["resets"]) or "• nothing"
        await interaction.response.edit_message(
            content=f"⚠️ **Sure?** Becoming Prestige {prestige.roman(st['next'] or 0)} resets, for good:\n{lost}\n"
                    "This can't be undone.",
            embed=None, view=ConfirmView(interaction.user.id, f"Prestige {prestige.roman(st['next'] or 0)}",
                                         self.cog.ascend))


class PrestigeCog(commands.Cog):
    """/prestige: start over for good bonuses."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._role_lock = asyncio.Lock()

    @app_commands.command(name="prestige", description="Prestige: what it needs, what you lose and what you get.")
    async def prestige_cmd(self, interaction: discord.Interaction):
        st = await self.bot.db.run(prestige.status, interaction.user.id)
        view = PrestigeView(self, interaction.user.id) if st["ready"] else None
        await interaction.response.send_message(embed=status_embed(st), view=view or discord.utils.MISSING,
                                                ephemeral=True)

    async def ascend(self, interaction: discord.Interaction) -> None:
        try:
            res = await self.bot.db.run(prestige.ascend, interaction.user.id)
        except Exception as error:
            return await report_error(interaction, error)
        await interaction.response.edit_message(
            content=f"🌟 You are now **Prestige {prestige.roman(res['prestige'])}**: +{res['bonus']:.0%} mining XP "
                    "and /sell for good. Good luck on the way back up!", embed=None, view=None)
        # The public announcement comes from the PrestigeReached notice (utils/announcer.py).

    async def after_change(self, user_id: int | None = None) -> None:
        await self.sync_role()
        dims = self.bot.get_cog("DimensionsCog")
        if dims is not None and user_id is not None:
            await dims.sync_roles(user_id)  # type: ignore[attr-defined]

    @commands.Cog.listener()
    async def on_blocky_prestige(self, user_id: int) -> None:
        await self.after_change(user_id)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.sync_role()

    @commands.Cog.listener()
    async def on_blocky_config_changed(self, key: str, before) -> None:
        if key == "role_prestige":
            await self.sync_role(int(before or 0))

    async def sync_role(self, old_role_id: int = 0) -> None:
        """roles.prestige on every player with a prestige, and on nobody else."""
        guild = getattr(self.bot, "main_guild", None)
        if guild is None:
            return
        async with self._role_lock:
            holders = set(await self.bot.db.run(prestige.holders))
            rid = role_id("prestige")
            changes: list[tuple[discord.Member, discord.Role, bool]] = []
            old = guild.get_role(old_role_id) if old_role_id and old_role_id != rid else None
            if old is not None:
                changes += [(m, old, False) for m in old.members]
            role = guild.get_role(rid) if rid else None
            if rid and role is None:
                log.warning("roles.prestige %s not found", rid)
            if role is not None:
                changes += [(m, role, False) for m in role.members if m.id not in holders]
                for uid in holders:
                    member = guild.get_member(uid)
                    if member is not None and role not in member.roles:
                        changes.append((member, role, True))
            for member, r, give in changes:
                try:
                    if give:
                        await member.add_roles(r, reason="Blocky: prestige")
                    else:
                        await member.remove_roles(r, reason="Blocky: no prestige")
                except discord.HTTPException:
                    log.warning("Could not update the prestige role of %s (check Manage Roles and role order)", member)

    async def staff_set(self, interaction: discord.Interaction, member: discord.Member, n: int) -> None:
        """/player prestige (cogs/staff_economy.py)."""
        n = await self.bot.db.run(prestige.set_prestige, member.id, n)
        await interaction.response.send_message(f"✅ {member.mention} is now Prestige **{prestige.roman(n) or '0'}** "
                                                "(nothing was reset).", ephemeral=True)
        await self.bot.announcer.send(f"🔧 {interaction.user.mention} set {member.mention}'s prestige to {n}.",
                                      channel="staff_log")
        await self.sync_role()


async def setup(bot: commands.Bot):
    await bot.add_cog(PrestigeCog(bot))
