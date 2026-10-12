from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from game import settings, species
from game.errors import GameError
from utils.config import role_id
from utils.ui import ConfirmView, em

log = logging.getLogger("species")

SPECIES_CHOICES = [app_commands.Choice(name=f"{s.emoji} {s.name}", value=s.key) for s in species.SPECIES.values()]


def species_roles(guild: discord.Guild) -> dict[str, discord.Role]:
    """species -> its role (roles.species_<key>), for the roles that are set and exist."""
    out = {}
    for key in species.SPECIES:
        rid = role_id(f"species_{key}")
        role = guild.get_role(rid) if rid else None
        if rid and role is None:
            log.warning("roles.species_%s %s not found", key, rid)
        if role is not None:
            out[key] = role
    return out


class SpeciesCog(commands.Cog):
    """/species: pick a species for a small bonus. A role per species, if the server set them."""

    group = app_commands.Group(name="species", description="Species: pick one for a small bonus.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._role_lock = asyncio.Lock()

    # ---------- roles ----------
    async def sync_roles(self, user_id: int | None = None, old_role_id: int = 0) -> None:
        """Give each player the role of their species and take the other species roles back.

        `user_id`: only this player. `old_role_id`: a role set before a /config change, taken back from everyone.
        """
        guild = getattr(self.bot, "main_guild", None)
        if guild is None:
            return
        async with self._role_lock:
            if user_id is None:
                kinds = await self.bot.db.run(species.all_species)
            else:
                kind = await self.bot.db.run(species.of, user_id)
                kinds = {user_id: kind} if kind else {}
            roles = species_roles(guild)
            changes: list[tuple[discord.Member, discord.Role, bool]] = []  # (member, role, give)
            old = guild.get_role(old_role_id) if old_role_id else None
            if old is not None and old not in roles.values():
                changes += [(m, old, False) for m in old.members if user_id in (None, m.id)]
            for key, role in roles.items():
                changes += [(m, role, False) for m in role.members
                            if user_id in (None, m.id) and kinds.get(m.id) != key]
            targets = kinds.items() if user_id is None else [(user_id, kinds.get(user_id))]
            for uid, key in targets:
                role = roles.get(key) if key else None
                member = guild.get_member(uid) if role else None
                if member is not None and role not in member.roles:
                    changes.append((member, role, True))
            for member, role, give in changes:
                try:
                    if give:
                        await member.add_roles(role, reason="Blocky: species")
                    else:
                        await member.remove_roles(role, reason="Blocky: species changed")
                except discord.HTTPException:
                    log.warning("Could not update the species role of %s (check Manage Roles and role order)", member)

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
        if key.startswith("role_species_"):
            await self.sync_roles(old_role_id=int(before or 0))

    # ---------- commands ----------
    @group.command(name="list", description="The species, their bonus and how many players chose each.")
    async def list_species(self, interaction: discord.Interaction):
        def load(ctx):
            return species.counts(ctx), species.change_terms(ctx, interaction.user.id)

        counts, terms = await self.bot.db.run(load)
        lines = [
            f"{s.emoji} **{s.name}** — {species.describe(s.key)} · {counts[s.key]} player(s)"
            for s in species.SPECIES.values()
        ]
        embed = discord.Embed(title="🧬 Species", description="\n".join(lines), color=discord.Color.blurple())
        if terms["current"]:
            when = "now" if terms["ready"] else f"<t:{terms['ready_at']}:R>"
            mine = f"{species.label(terms['current'])}. Change for {em(terms['cost'])} (possible {when})."
        else:
            mine = "None yet. Your first choice is free: `/species choose`."
        embed.add_field(name="You", value=mine, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="choose", description="Pick your species (the first choice is free).")
    @app_commands.describe(kind="The species you want")
    @app_commands.rename(kind="species")
    @app_commands.choices(kind=SPECIES_CHOICES)
    async def choose(self, interaction: discord.Interaction, kind: str):
        user = interaction.user
        terms = await self.bot.db.run(species.change_terms, user.id)

        async def do(i: discord.Interaction, edit: bool) -> None:
            res = await self.bot.db.run(species.choose, user.id, kind)
            text = f"🧬 {user.mention} is now a **{species.label(kind)}**: {species.describe(kind)}."
            if res["cost"]:
                text += f" (-{em(res['cost'])})"
            if edit:
                await i.response.edit_message(content="Done.", view=None)
                await i.followup.send(text, allowed_mentions=discord.AllowedMentions.none())
            else:
                await i.response.send_message(text, allowed_mentions=discord.AllowedMentions.none())
            await self.sync_roles(user.id)

        if terms["current"] is None or terms["current"] == kind:
            await do(interaction, edit=False)  # free first choice (or the error "already a …")
            return
        if not terms["ready"]:
            raise GameError(f"You can change your species again <t:{terms['ready_at']}:R>.")
        await interaction.response.send_message(
            f"Change from **{species.label(terms['current'])}** to **{species.label(kind)}** for {em(terms['cost'])}? "
            f"Next change possible in {float(settings.get()['species']['change_days']):g} day(s).",
            view=ConfirmView(user.id, "Change", lambda i: do(i, edit=True)), ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SpeciesCog(bot))
