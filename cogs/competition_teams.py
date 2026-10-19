from __future__ import annotations

import asyncio
import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.player_profile import banner_file
from game import profiles, settings, team_spaces, teams, war
from game.errors import GameError
from utils.checks import staff_only
from utils.config import role_id, staff_role_id
from utils.ui import ConfirmView, em, report_error, tag_prefix

log = logging.getLogger("teams")

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
NO_PINGS = discord.AllowedMentions.none()
DYE_CHOICES = [app_commands.Choice(name=name, value=key) for key, (name, _) in profiles.DYES.items()]
PATTERN_CHOICES = [app_commands.Choice(name=label, value=key) for key, label in profiles.PATTERNS.items()]


CHANNEL_LIMIT = 490  # Discord allows 500 channels per server: keep some room for the staff
KIND_CHOICES = [app_commands.Choice(name="Text", value="text"), app_commands.Choice(name="Voice", value="voice")]


def team_label(team: dict) -> str:
    return f"**[{team['tag']}] {team['name']}**"


def space_name(team: dict) -> str:
    """The name of a team's role and category."""
    return f"[{team['tag']}] {team['name']}"


def space_overwrites(guild: discord.Guild, role: discord.Role) -> dict:
    """A team category: its members (the team role) and the staff see it, nobody else.

    Only what's needed is allowed (the rest comes from the members' server roles): Discord refuses an
    overwrite allowing a permission the bot doesn't have itself."""
    out: dict = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                          connect=True, speak=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                              connect=True),
    }
    staff = guild.get_role(staff_role_id())
    if staff is not None:
        out[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                                 manage_messages=True, connect=True, speak=True)
    return out


def check_room(guild: discord.Guild, needed: int) -> None:
    if len(guild.channels) + needed > CHANNEL_LIMIT:
        raise GameError("The server is close to Discord's limit of 500 channels: no room for more team channels.")


class TeamInviteButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"blocky:team:(?P<action>accept|decline):(?P<team_id>\d+):(?P<user_id>\d+)",
):
    """Join / Decline buttons of an invitation. They survive restarts."""

    def __init__(self, action: str, team_id: int, user_id: int) -> None:
        accept = action == "accept"
        super().__init__(
            discord.ui.Button(
                label="Join the team" if accept else "Decline",
                style=discord.ButtonStyle.success if accept else discord.ButtonStyle.secondary,
                emoji="✅" if accept else None,
                custom_id=f"blocky:team:{action}:{team_id}:{user_id}",
            )
        )
        self.action, self.team_id, self.user_id = action, team_id, user_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(match["action"], int(match["team_id"]), int(match["user_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: TeamsCog | None = interaction.client.get_cog("TeamsCog")  # type: ignore[assignment]
        if cog is None:
            return
        try:
            if interaction.user.id != self.user_id:
                raise GameError("This invitation isn't for you.")
            await cog.answer_invite(interaction, self.action == "accept", self.team_id)
        except Exception as error:
            await report_error(interaction, error)


def invite_view(team_id: int, user_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(TeamInviteButton("accept", team_id, user_id))
    view.add_item(TeamInviteButton("decline", team_id, user_id))
    return view


class TeamsCog(commands.Cog):
    team = app_commands.Group(name="team", description="Teams: play together and win the weekly team season.")
    channel = app_commands.Group(name="channel", description="LEADER: The channels of your team's category.",
                                 parent=team)
    chest = app_commands.Group(name="chest", description="Your team's chest: emeralds for the gang war.", parent=team)

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._role_lock = asyncio.Lock()
        self._space_lock = asyncio.Lock()

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(TeamInviteButton)
        self.space_loop.start()

    async def cog_unload(self) -> None:
        self.space_loop.cancel()
        self.bot.remove_dynamic_items(TeamInviteButton)

    async def after_change(self) -> None:
        """After a team changes (members, leader, name, deleted): the leader role and the team spaces follow."""
        await self.sync_leader_role()
        await self.sync_spaces()

    async def say(self, interaction: discord.Interaction, text: str) -> None:
        """Public answer that shows names without pinging anyone."""
        await interaction.response.send_message(text, allowed_mentions=NO_PINGS)

    # ---------- team leader role ----------
    async def sync_leader_role(self, old_role_id: int = 0) -> None:
        """Give roles.team_leader to every team leader and take it back from everyone else.

        `old_role_id`: the role set before a /config change, taken back from everyone.
        """
        guild = getattr(self.bot, "main_guild", None)
        if guild is None:
            return
        async with self._role_lock:
            leaders = await self.bot.db.run(teams.leader_ids)
            rid = role_id("team_leader")
            changes: list[tuple[discord.Member, discord.Role, bool]] = []  # (member, role, give)
            old = guild.get_role(old_role_id) if old_role_id and old_role_id != rid else None
            if old is not None:
                changes += [(m, old, False) for m in old.members]
            role = guild.get_role(rid) if rid else None
            if rid and role is None:
                log.warning("roles.team_leader %s not found", rid)
            if role is not None:
                changes += [(m, role, False) for m in role.members if m.id not in leaders]
                for uid in leaders:
                    member = guild.get_member(uid)
                    if member is not None and role not in member.roles:
                        changes.append((member, role, True))
            for member, r, give in changes:
                try:
                    if give:
                        await member.add_roles(r, reason="Blocky: team leader")
                    else:
                        await member.remove_roles(r, reason="Blocky: no longer a team leader")
                except discord.HTTPException:
                    log.warning("Could not update the team leader role of %s (check Manage Roles and role order)", member)

    # ---------- team spaces (a private category per team) ----------
    async def sync_spaces(self) -> None:
        """Every team space: role and category named after the team, the role on exactly its members,
        and the spaces of teams that are gone deleted."""
        guild = getattr(self.bot, "main_guild", None)
        if guild is None:
            return
        async with self._space_lock:
            for space in await self.bot.db.run(team_spaces.every):
                try:
                    await self.sync_space(guild, space)
                except Exception:  # one team's problem never stops the others (nor the loop)
                    log.warning("Could not update the space of team %s (check Manage Channels and Manage Roles, "
                                "and the 500-channel limit)", space["team_id"], exc_info=True)

    async def sync_space(self, guild: discord.Guild, space: dict) -> None:
        role = guild.get_role(space["role_id"]) if space["role_id"] else None
        found = guild.get_channel(space["category_id"]) if space["category_id"] else None
        category = found if isinstance(found, discord.CategoryChannel) else None
        team = space["team"]
        if team is None:  # disbanded or deleted by the staff
            await self.delete_space(category, role)
            await self.bot.db.run(team_spaces.forget, space["team_id"])
            return
        if not space["category_id"]:
            # Being unlocked right now; still not made after 10 minutes (the bot restarted meanwhile): refunded.
            if time.time() - space["unlocked_at"] > 600:
                back = await self.bot.db.run(team_spaces.refund, space["team_id"])
                log.warning("Team %s's category was never made: %s emeralds refunded", space["team_id"], back)
            return
        name = space_name(team)
        if role is None:
            role = await guild.create_role(name=name, reason="Blocky: team role (it was missing)")
        elif role.name != name:
            await role.edit(name=name, reason="Blocky: team renamed")
        if category is None:
            check_room(guild, 2)
            category = await self.make_category(guild, role, name)  # deleted by hand: made again
        else:
            if category.name != name:
                await category.edit(name=name, reason="Blocky: team renamed")
            wanted = space_overwrites(guild, role)
            if any(category.overwrites.get(target) != perms for target, perms in wanted.items()):
                await category.edit(overwrites={**category.overwrites, **wanted}, reason="Blocky: team category")
                for child in category.channels:
                    await child.edit(sync_permissions=True, reason="Blocky: team category")
        if (role.id, category.id) != (space["role_id"], space["category_id"]):
            await self.bot.db.run(team_spaces.set_discord, space["team_id"], role.id, category.id)
        members = set(space["members"])
        for member in role.members:
            if member.id not in members:
                await member.remove_roles(role, reason="Blocky: left the team")
        for uid in members:
            member = guild.get_member(uid)
            if member is not None and role not in member.roles:
                await member.add_roles(role, reason="Blocky: team member")

    async def make_category(self, guild: discord.Guild, role: discord.Role, name: str) -> discord.CategoryChannel:
        category = await guild.create_category(name, overwrites=space_overwrites(guild, role),
                                               reason="Blocky: team category")
        await category.create_text_channel("chat", overwrites=category.overwrites, reason="Blocky: team category")
        return category

    async def delete_space(self, category: discord.CategoryChannel | None, role: discord.Role | None) -> None:
        if category is not None:
            for child in category.channels:
                await child.delete(reason="Blocky: the team is gone")
            await category.delete(reason="Blocky: the team is gone")
        if role is not None:
            await role.delete(reason="Blocky: the team is gone")

    @tasks.loop(minutes=30)
    async def space_loop(self) -> None:
        try:
            await self.sync_spaces()  # repairs what was changed by hand (a deleted role or category…)
        except Exception:  # never let the loop die
            log.exception("Team spaces loop failed")

    @space_loop.before_loop
    async def before_space_loop(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.after_change()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = getattr(self.bot, "main_guild", None)
        if guild is not None and member.guild.id == guild.id:
            await self.after_change()  # a member coming back gets their team role again

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Leaving the server leaves the team: a departed leader would freeze it (nobody could invite,
        kick or transfer), and a departed member would hold a place forever."""
        guild = getattr(self.bot, "main_guild", None)
        if guild is None or member.guild.id != guild.id:
            return
        if await self.bot.db.run(teams.team_of, member.id) is None:
            return
        res = await self.bot.db.run(teams.leave, member.id)
        log.info("%s left the server and team %s", member, res["team"]["tag"])
        await self.after_change()

    @commands.Cog.listener()
    async def on_blocky_config_changed(self, key: str, before) -> None:
        if key == "role_team_leader":
            await self.sync_leader_role(int(before or 0))

    # ---------- autocomplete ----------
    async def team_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = await self.bot.db.run(teams.search, current)
        return [app_commands.Choice(name=f"[{t['tag']}] {t['name']}", value=t["tag"]) for t in rows][:25]

    async def invite_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = await self.bot.db.run(teams.pending_invites, interaction.user.id)
        choices = []
        for t in rows:
            name = f"[{t['tag']}] {t['name']}"
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name, value=t["tag"]))
        return choices[:25]

    # ---------- membership ----------
    @team.command(name="create", description="Create a team and become its leader.")
    @app_commands.describe(
        name=f"Team name ({teams.NAME_MIN}-{teams.NAME_MAX} characters)",
        tag="2 to 4 letters or numbers shown next to your name, e.g. ABC",
    )
    async def create(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 40], tag: app_commands.Range[str, 1, 6]):
        team = await self.bot.db.run(teams.create, interaction.user.id, name, tag)
        cost = int(settings.get()["teams"]["create_cost"])
        paid = f" (-{em(cost)})" if cost else ""
        await self.say(
            interaction,
            f"🛡️ {interaction.user.mention} created the team {team_label(team)}{paid}! "
            f"Invite up to {teams.max_members() - 1} players with `/team invite`.",
        )
        await self.sync_leader_role()

    @team.command(name="invite", description="LEADER: Invite a player to your team.")
    @app_commands.describe(member="Who you want in your team")
    async def invite(self, interaction: discord.Interaction, member: discord.Member):
        if member.bot:
            raise GameError("Bots don't play.")
        res = await self.bot.db.run(teams.invite, interaction.user.id, member.id)
        team = res["team"]
        embed = discord.Embed(
            title="🛡️ Team invitation",
            description=(
                f"{interaction.user.mention} invites {member.mention} to join {team_label(team)} "
                f"({res['members']}/{teams.max_members()} members).\n\n"
                f"Expires <t:{res['expires_at']}:R>. You can also accept later with `/team join {team['tag']}`."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(
            content=member.mention, embed=embed, view=invite_view(team["team_id"], member.id),
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=[member]),
        )

    async def answer_invite(self, interaction: discord.Interaction, accept: bool, team_id: int) -> None:
        user = interaction.user
        if accept:
            res = await self.bot.db.run(teams.accept, user.id, team_id)
            embed = discord.Embed(
                description=f"✅ {user.mention} joined {team_label(res['team'])}! ({res['members']}/{teams.max_members()})",
                color=discord.Color.green(),
            )
        else:
            await self.bot.db.run(teams.decline, user.id, team_id)
            embed = discord.Embed(description=f"✖️ {user.mention} declined the invitation.", color=discord.Color.dark_grey())
        await interaction.response.edit_message(content=None, embed=embed, view=None)
        if accept:
            await self.after_change()

    @team.command(name="join", description="Accept a team invitation.")
    @app_commands.describe(team="The team that invited you")
    @app_commands.autocomplete(team=invite_autocomplete)
    async def join(self, interaction: discord.Interaction, team: str):
        res = await self.bot.db.run(teams.join, interaction.user.id, team)
        await self.say(
            interaction,
            f"✅ {interaction.user.mention} joined {team_label(res['team'])}! ({res['members']}/{teams.max_members()})",
        )
        await self.after_change()

    @team.command(name="leave", description="Leave your team.")
    async def leave(self, interaction: discord.Interaction):
        user = interaction.user
        team = await self.bot.db.run(teams.team_of, user.id)
        if team is None:
            raise GameError("You are not in a team.")

        async def do(i: discord.Interaction) -> None:
            res = await self.bot.db.run(teams.leave, user.id)
            label = team_label(res["team"])
            if res["disbanded"]:
                text = f"👋 {user.mention} left {label}: the team is disbanded."
            elif res["new_leader"]:
                text = f"👋 {user.mention} left {label}. <@{res['new_leader']}> is the new leader."
            else:
                text = f"👋 {user.mention} left {label}."
            await i.response.edit_message(content="Done.", view=None)
            await i.followup.send(text, allowed_mentions=NO_PINGS)
            await self.after_change()

        warning = ""
        if team["leader_id"] == user.id:
            warning = "\nYou are the leader: the oldest member becomes leader (if you are alone, the team is disbanded)."
        await interaction.response.send_message(
            f"Leave {team_label(team)}? What you earned for the team this week still counts, "
            f"and you keep your share of its reward.{warning}",
            view=ConfirmView(user.id, "Leave", do), ephemeral=True,
        )

    # ---------- leader ----------
    @team.command(name="kick", description="LEADER: Remove a member from your team.")
    @app_commands.describe(member="The member to remove")
    async def kick(self, interaction: discord.Interaction, member: discord.Member):
        team = await self.bot.db.run(teams.kick, interaction.user.id, member.id)
        await self.say(interaction, f"🚪 {member.mention} was removed from {team_label(team)} by {interaction.user.mention}.")
        await self.after_change()

    @team.command(name="transfer", description="LEADER: Make another member the leader.")
    @app_commands.describe(member="The new leader")
    async def transfer(self, interaction: discord.Interaction, member: discord.Member):
        team = await self.bot.db.run(teams.transfer, interaction.user.id, member.id)
        await self.say(interaction, f"👑 {member.mention} is the new leader of {team_label(team)}.")
        await self.after_change()

    @team.command(name="rename", description="LEADER: Change the name and/or the tag of your team.")
    @app_commands.describe(name="New name (leave empty to keep it)", tag="New tag (leave empty to keep it)")
    async def rename(
        self, interaction: discord.Interaction,
        name: app_commands.Range[str, 1, 40] | None = None, tag: app_commands.Range[str, 1, 6] | None = None,
    ):
        res = await self.bot.db.run(teams.rename, interaction.user.id, name, tag)
        await self.say(interaction, f"✏️ {team_label(res['before'])} is now {team_label(res['after'])}.")
        await self.after_change()

    @team.command(name="disband", description="LEADER: Delete your team.")
    async def disband(self, interaction: discord.Interaction):
        user = interaction.user
        team = await self.bot.db.run(teams.team_of, user.id)
        if team is None:
            raise GameError("You are not in a team.")
        if team["leader_id"] != user.id:
            raise GameError(f"Only the leader (<@{team['leader_id']}>) can disband the team.")

        async def do(i: discord.Interaction) -> None:
            res = await self.bot.db.run(teams.disband, user.id)
            await i.response.edit_message(content="Done.", view=None)
            await i.followup.send(f"💥 {team_label(res)} was disbanded by {user.mention}.", allowed_mentions=NO_PINGS)
            await self.after_change()

        await interaction.response.send_message(
            f"Disband {team_label(team)}? Every member leaves the team and this week's team score is lost. "
            "This can't be undone.",
            view=ConfirmView(user.id, "Disband", do), ephemeral=True,
        )

    # ---------- the team's category ----------
    @team.command(name="category", description="LEADER: Unlock your team's private category, where you create channels.")
    async def category(self, interaction: discord.Interaction):
        user, guild = interaction.user, interaction.guild
        if guild is None:
            raise GameError("Use this in the server.")
        team = await self.bot.db.run(team_spaces.check_unlock, user.id)
        check_room(guild, 2)
        price, limit = team_spaces.cost(), team_spaces.max_channels()

        async def do(i: discord.Interaction) -> None:
            await i.response.edit_message(content="⏳ Creating your team's category…", view=None)
            res = await self.bot.db.run(team_spaces.unlock, user.id)
            role = None
            try:
                async with self._space_lock:
                    role = await guild.create_role(name=space_name(team), reason="Blocky: team role")
                    category = await self.make_category(guild, role, space_name(team))
                    await self.bot.db.run(team_spaces.set_discord, team["team_id"], role.id, category.id)
            except discord.HTTPException:
                log.warning("Could not create the category of team %s", team["team_id"], exc_info=True)
                if role is not None:
                    try:
                        await role.delete(reason="Blocky: team category failed")
                    except discord.HTTPException:
                        pass
                back = await self.bot.db.run(team_spaces.refund, team["team_id"])
                await i.followup.send(
                    "❌ I couldn't create the category (I need the *Manage Channels* and *Manage Roles* "
                    f"permissions). You got your {em(back)} back.", ephemeral=True,
                )
                return
            await self.sync_spaces()  # the members get the team role
            await i.followup.send(
                f"🏠 {team_label(team)} has its own category: {category.channels[0].mention}. Only your members and "
                f"the staff see it. Create up to {limit} channels with `/team channel create`."
                + (f" (-{em(res['paid'])})" if res["paid"] else ""),
                allowed_mentions=NO_PINGS,
            )

        await interaction.response.send_message(
            f"Unlock a private category for {team_label(team)}? Only your members and the staff see it, and you (the "
            f"leader) create up to **{limit}** text and voice channels in it with `/team channel create`. "
            f"Price: {em(price)}, once.",
            view=ConfirmView(user.id, f"Unlock ({price:,})", do), ephemeral=True,
        )

    async def leader_category(self, interaction: discord.Interaction) -> tuple[dict, discord.CategoryChannel]:
        res = await self.bot.db.run(team_spaces.leader_space, interaction.user.id)
        guild = interaction.guild
        found = guild.get_channel(res["space"]["category_id"]) if guild is not None else None
        if not isinstance(found, discord.CategoryChannel):
            await self.sync_spaces()
            raise GameError("Your team's category was missing: it was made again, try once more.")
        return res["team"], found

    async def team_channel_autocomplete(self, interaction: discord.Interaction, current: str):
        try:
            _, category = await self.leader_category(interaction)
        except GameError:
            return []
        return [
            app_commands.Choice(name=("🔊 " if isinstance(c, discord.VoiceChannel) else "# ") + c.name, value=str(c.id))
            for c in category.channels if current.lower() in c.name.lower()
        ][:25]

    async def team_channel(self, interaction: discord.Interaction, value: str) -> tuple[dict, discord.CategoryChannel,
                                                                                      discord.abc.GuildChannel]:
        team, category = await self.leader_category(interaction)
        channel = interaction.guild.get_channel(int(value)) if value.isdigit() else None  # type: ignore[union-attr]
        if channel is None or getattr(channel, "category_id", None) != category.id:
            raise GameError("Pick one of your team's channels (the suggestions).")
        return team, category, channel

    @channel.command(name="create", description="LEADER: Create a text or voice channel in your team's category.")
    @app_commands.describe(name="The channel's name", kind="Text or voice (text by default)")
    @app_commands.choices(kind=KIND_CHOICES)
    async def channel_create(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 40],
                             kind: str = "text"):
        team, category = await self.leader_category(interaction)
        limit = team_spaces.max_channels()
        if len(category.channels) >= limit:
            raise GameError(f"Your category has {limit} channels at most: delete one first (`/team channel delete`).")
        check_room(interaction.guild, 1)  # type: ignore[arg-type]
        await interaction.response.defer(ephemeral=True, thinking=True)
        make = category.create_voice_channel if kind == "voice" else category.create_text_channel
        channel = await make(name, overwrites=category.overwrites, reason=f"Blocky: team channel ({interaction.user})")
        await interaction.followup.send(f"✅ {channel.mention} created in {team_label(team)}.", ephemeral=True)

    @channel.command(name="rename", description="LEADER: Rename one of your team's channels.")
    @app_commands.describe(channel="One of your team's channels", name="Its new name")
    @app_commands.autocomplete(channel=team_channel_autocomplete)
    async def channel_rename(self, interaction: discord.Interaction, channel: str, name: app_commands.Range[str, 1, 40]):
        _, _, target = await self.team_channel(interaction, channel)
        await interaction.response.defer(ephemeral=True, thinking=True)
        await target.edit(name=name, reason=f"Blocky: team channel renamed ({interaction.user})")
        await interaction.followup.send(f"✏️ Renamed: {target.mention}.", ephemeral=True)

    @channel.command(name="delete", description="LEADER: Delete one of your team's channels.")
    @app_commands.describe(channel="One of your team's channels")
    @app_commands.autocomplete(channel=team_channel_autocomplete)
    async def channel_delete(self, interaction: discord.Interaction, channel: str):
        _, category, target = await self.team_channel(interaction, channel)
        if len(category.channels) <= 1:
            raise GameError("Your category needs at least one channel: create another one first.")

        async def do(i: discord.Interaction) -> None:
            await target.delete(reason=f"Blocky: team channel deleted ({interaction.user})")
            await i.response.edit_message(content=f"🗑️ **{target.name}** was deleted.", view=None)

        await interaction.response.send_message(
            f"Delete {target.mention}? Its messages are lost for good.",
            view=ConfirmView(interaction.user.id, "Delete", do), ephemeral=True,
        )

    # ---------- information ----------
    @team.command(name="info", description="Show a team: members, weekly score and bonus.")
    @app_commands.describe(team="Tag or name of the team (yours by default)")
    @app_commands.autocomplete(team=team_autocomplete)
    async def info(self, interaction: discord.Interaction, team: str | None = None):
        user_id = interaction.user.id

        def load(ctx):
            found = teams.find_team(ctx, team) if team else teams.team_of(ctx, user_id)
            if found is None:
                raise GameError("You are not in a team. Give a team tag to look at another team.")
            return teams.overview(ctx, found["team_id"])

        data = await self.bot.db.run(load)
        t = data["team"]
        lines = [
            ("👑 " if m["is_leader"] else "") + tag_prefix({}, m["user_id"], data["species"])
            + f"<@{m['user_id']}> — {em(m['score'])} this week" + (" ⛏️" if m["active"] else "")
            for m in data["members"]
        ]
        embed = discord.Embed(
            title=f"🛡️ [{t['tag']}] {t['name']}",
            description=f"Created <t:{t['created_at']}:D>",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name=f"Members ({len(lines)}/{data['max_members']})", value="\n".join(lines) or "—", inline=False
        )
        season = f"#{data['rank']} of {data['teams_ranked']} — **{data['score']:,} pts**" if data["rank"] else "Not ranked yet"
        embed.add_field(name="Team season", value=f"{season}\nEnds <t:{data['ends_at']}:R>", inline=True)
        max_bonus = float(settings.get()["teams"]["max_xp_bonus"])
        if data["bonus"] > 0:
            bonus = f"{data['active_today']} mined today → **+{data['bonus']:.0%} XP** each"
        else:
            bonus = f"{data['active_today']} mined today. Mine together for up to **+{max_bonus:.0%} XP**."
        embed.add_field(name="Team bonus", value=bonus, inline=True)
        embed.add_field(name="💰 Chest", value=em(int(t.get("chest") or 0)), inline=True)
        if data["wins"]:
            embed.add_field(name="🏆 Team seasons won", value=str(data["wins"]), inline=True)
        space = await self.bot.db.run(team_spaces.get, t["team_id"])
        found = interaction.guild.get_channel(space["category_id"]) if space and space["category_id"] and interaction.guild else None
        if isinstance(found, discord.CategoryChannel):
            where = " ".join(c.mention for c in found.channels) or "—"
            embed.add_field(name="🏠 Team category", value=f"{where}\n(members and staff only)", inline=False)
        else:
            embed.add_field(name="🏠 Team category", value=f"Not unlocked yet: `/team category` (leader, "
                                                         f"{em(team_spaces.cost())})", inline=False)
        embed.set_footer(text="⛏️ = mined today")
        file = banner_file(data["banner"]) if data.get("banner") else None
        if file is None:
            await interaction.response.send_message(embed=embed)
            return
        embed.set_thumbnail(url="attachment://banner.png")
        await interaction.response.send_message(embed=embed, file=file)

    # ---------- chest and raids (gang wars, game/war.py) ----------
    @chest.command(name="deposit", description="Put emeralds in your team's chest (safe from /rob, not from raids).")
    @app_commands.describe(amount="Emeralds to put in")
    async def chest_deposit(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1]):
        res = await self.bot.db.run(war.deposit, interaction.user.id, amount)
        await interaction.response.send_message(
            f"💰 {interaction.user.mention} put {em(amount)} in **[{res['team']['tag']}]**'s chest "
            f"(now {em(res['chest'])}).", allowed_mentions=discord.AllowedMentions.none())

    @chest.command(name="withdraw", description="LEADER: Take emeralds out of your team's chest.")
    @app_commands.describe(amount="Emeralds to take out")
    async def chest_withdraw(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1]):
        res = await self.bot.db.run(war.withdraw, interaction.user.id, amount)
        await interaction.response.send_message(
            f"💰 {interaction.user.mention} took {em(amount)} out of **[{res['team']['tag']}]**'s chest "
            f"(now {em(res['chest'])}).", allowed_mentions=discord.AllowedMentions.none())

    @chest.command(name="view", description="Your team's chest, and what the gang war takes and gives.")
    async def chest_view(self, interaction: discord.Interaction):
        def load(ctx):
            team = teams.team_of(ctx, interaction.user.id)
            if team is None:
                raise GameError("You're not in a team.")
            return team, war.chest(ctx, team["team_id"]), war.protected_until(ctx, team["team_id"])

        team, amount, safe = await self.bot.db.run(load)
        w = settings.get()["war"]
        text = (f"💰 **[{team['tag']}] {team['name']}**'s chest: {em(amount)}.\n"
                f"Members put emeralds in (`/team chest deposit`), only the leader takes them out. A personal /rob "
                f"can't reach it, but other teams can **raid** it (`/team raid`): {float(w['raid_steal']):.0%} of it "
                f"is taken when they win. Every Monday {float(w['levy']):.0%} of it goes into the gang war's pot "
                "(`/war`).")
        if safe:
            text += f"\n🛡️ Raided recently: safe until <t:{safe}:f>."
        await interaction.response.send_message(text, ephemeral=True)

    @team.command(name="raid", description="Raid another team's chest: gather your team, then fight its defenders.")
    @app_commands.describe(team="Tag or name of the team to raid")
    @app_commands.autocomplete(team=team_autocomplete)
    async def raid(self, interaction: discord.Interaction, team: str):
        cog = self.bot.get_cog("WarCog")
        if cog is None:
            raise GameError("Raids aren't available right now.")
        await cog.start_raid(interaction, team)  # type: ignore[attr-defined]

    @team.command(name="banner", description="LEADER: Design your team's banner (shown on the members' profiles).")
    @app_commands.describe(
        base="The banner's color", pattern1="A pattern (Minecraft banner patterns)", color1="Its color",
        pattern2="Another pattern, on top", color2="Its color", pattern3="A third pattern, on top", color3="Its color",
    )
    @app_commands.choices(
        base=DYE_CHOICES, color1=DYE_CHOICES, color2=DYE_CHOICES, color3=DYE_CHOICES,
        pattern1=PATTERN_CHOICES, pattern2=PATTERN_CHOICES, pattern3=PATTERN_CHOICES,
    )
    async def banner(
        self, interaction: discord.Interaction, base: str,
        pattern1: str | None = None, color1: str | None = None, pattern2: str | None = None,
        color2: str | None = None, pattern3: str | None = None, color3: str | None = None,
    ):
        user = interaction.user
        layers = [(p, c or "white") for p, c in ((pattern1, color1), (pattern2, color2), (pattern3, color3)) if p]
        design = profiles.check_banner(base, layers)
        team = await self.bot.db.run(teams.team_of, user.id)
        if team is None or team["leader_id"] != user.id:
            raise GameError("Only a team leader can change the team banner.")
        cost = int(settings.get()["profiles"]["banner_cost"])

        async def do(i: discord.Interaction) -> None:
            await self.bot.db.run(profiles.set_banner, user.id, design["base"], design["layers"])
            await i.response.edit_message(content=f"✅ New banner for {team_label(team)} (-{em(cost)}).", view=None)

        file = banner_file(design)
        await interaction.response.send_message(
            f"Save this banner for {team_label(team)} for {em(cost)}? It shows on every member's profile.",
            files=[file] if file else [], view=ConfirmView(user.id, f"Save ({cost:,})", do), ephemeral=True,
        )

    @team.command(name="top", description="This week's team season standings.")
    async def top(self, interaction: discord.Interaction):
        data = await self.bot.db.run(teams.season_overview, interaction.user.id)
        lines = [
            f"{MEDALS.get(i, f'`#{i}`')} {team_label(t)} — **{t['score']:,} pts** "
            f"({em(t['earned'])} by {t['members']} member{'s' if t['members'] > 1 else ''})"
            for i, t in enumerate(data["top"], start=1)
        ]
        rewards = " · ".join(f"{MEDALS.get(i, f'#{i}')} {em(r)}" for i, r in enumerate(data["rewards"], start=1))
        if settings.get()["teams"]["log_score"]:
            how = ("Score: what the members earned this week (same as /season), the best earner in full and the others "
                   "less and less, so 5 members earning the same score ×2.6, not ×5.")
        else:
            how = "Score: what the members earned this week (same as /season)."
        embed = discord.Embed(
            title=f"🛡️ Team season {data['season_id']}",
            description=(
                f"{how} The reward is shared between them, in proportion to what each one earned for the team.\n"
                f"Ends <t:{data['ends_at']}:R>. Rewards: {rewards}\n\n"
                + ("\n".join(lines) or "No team has scored yet. Be the first!")
            ),
            color=discord.Color.gold(),
        )
        if data["last_winner"]:
            w = data["last_winner"]
            embed.add_field(name="🚩 Last winner", value=f"{team_label(w)} ({w['season_id']})", inline=True)
        if data["team"]:
            mine = f"#{data['rank']} — {data['score']:,} pts" if data["rank"] else "Not ranked yet"
            embed.add_field(name=f"[{data['team']['tag']}] {data['team']['name']}", value=mine, inline=True)
        else:
            embed.add_field(name="Your team", value="You are not in a team: `/team create`", inline=True)
        await interaction.response.send_message(embed=embed)

    # ---------- staff ----------
    @app_commands.command(name="team_remove", description="STAFF: Delete a team (offensive name...).")
    @app_commands.describe(team="Tag or name of the team")
    @app_commands.autocomplete(team=team_autocomplete)
    @staff_only()
    async def team_remove(self, interaction: discord.Interaction, team: str):
        res = await self.bot.db.run(teams.remove, team)
        await interaction.response.send_message(
            f"✅ {team_label(res)} deleted ({len(res['members'])} members).", ephemeral=True
        )
        embed = discord.Embed(
            title="🛡️ Team deleted",
            description=f"{team_label(res)} was deleted by {interaction.user.mention} (`{interaction.user}`).",
            color=discord.Color.orange(),
        )
        await self.bot.announcer.send(embed=embed, channel="staff_log")
        await self.after_change()


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamsCog(bot))
