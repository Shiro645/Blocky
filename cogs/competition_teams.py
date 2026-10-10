from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from game import settings, teams
from game.errors import GameError
from utils.checks import staff_only
from utils.ui import ConfirmView, em, report_error

log = logging.getLogger("teams")

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
NO_PINGS = discord.AllowedMentions.none()


def team_label(team: dict) -> str:
    return f"**[{team['tag']}] {team['name']}**"


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

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(TeamInviteButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(TeamInviteButton)

    async def say(self, interaction: discord.Interaction, text: str) -> None:
        """Public answer that shows names without pinging anyone."""
        await interaction.response.send_message(text, allowed_mentions=NO_PINGS)

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

    @team.command(name="join", description="Accept a team invitation.")
    @app_commands.describe(team="The team that invited you")
    @app_commands.autocomplete(team=invite_autocomplete)
    async def join(self, interaction: discord.Interaction, team: str):
        res = await self.bot.db.run(teams.join, interaction.user.id, team)
        await self.say(
            interaction,
            f"✅ {interaction.user.mention} joined {team_label(res['team'])}! ({res['members']}/{teams.max_members()})",
        )

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

    @team.command(name="transfer", description="LEADER: Make another member the leader.")
    @app_commands.describe(member="The new leader")
    async def transfer(self, interaction: discord.Interaction, member: discord.Member):
        team = await self.bot.db.run(teams.transfer, interaction.user.id, member.id)
        await self.say(interaction, f"👑 {member.mention} is the new leader of {team_label(team)}.")

    @team.command(name="rename", description="LEADER: Change the name and/or the tag of your team.")
    @app_commands.describe(name="New name (leave empty to keep it)", tag="New tag (leave empty to keep it)")
    async def rename(
        self, interaction: discord.Interaction,
        name: app_commands.Range[str, 1, 40] | None = None, tag: app_commands.Range[str, 1, 6] | None = None,
    ):
        res = await self.bot.db.run(teams.rename, interaction.user.id, name, tag)
        await self.say(interaction, f"✏️ {team_label(res['before'])} is now {team_label(res['after'])}.")

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

        await interaction.response.send_message(
            f"Disband {team_label(team)}? Every member leaves the team and this week's team score is lost. "
            "This can't be undone.",
            view=ConfirmView(user.id, "Disband", do), ephemeral=True,
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
            ("👑 " if m["is_leader"] else "") + f"<@{m['user_id']}> — {em(m['score'])} this week" + (" ⛏️" if m["active"] else "")
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
        season = f"#{data['rank']} of {data['teams_ranked']} — {em(data['score'])}" if data["rank"] else "Not ranked yet"
        embed.add_field(name="Team season", value=f"{season}\nEnds <t:{data['ends_at']}:R>", inline=True)
        max_bonus = float(settings.get()["teams"]["max_xp_bonus"])
        if data["bonus"] > 0:
            bonus = f"{data['active_today']} mined today → **+{data['bonus']:.0%} XP** each"
        else:
            bonus = f"{data['active_today']} mined today. Mine together for up to **+{max_bonus:.0%} XP**."
        embed.add_field(name="Team bonus", value=bonus, inline=True)
        if data["wins"]:
            embed.add_field(name="🏆 Team seasons won", value=str(data["wins"]), inline=True)
        embed.set_footer(text="⛏️ = mined today")
        await interaction.response.send_message(embed=embed)

    @team.command(name="top", description="This week's team season standings.")
    async def top(self, interaction: discord.Interaction):
        data = await self.bot.db.run(teams.season_overview, interaction.user.id)
        lines = [
            f"{MEDALS.get(i, f'`#{i}`')} {team_label(t)} — **{em(t['score'])}**"
            for i, t in enumerate(data["top"], start=1)
        ]
        rewards = " · ".join(f"{MEDALS.get(i, f'#{i}')} {em(r)}" for i, r in enumerate(data["rewards"], start=1))
        embed = discord.Embed(
            title=f"🛡️ Team season {data['season_id']}",
            description=(
                "Score = what the members created this week (same as /season). The reward is shared between them, "
                "in proportion to what each one earned for the team.\n"
                f"Ends <t:{data['ends_at']}:R>. Rewards: {rewards}\n\n"
                + ("\n".join(lines) or "No team has scored yet. Be the first!")
            ),
            color=discord.Color.gold(),
        )
        if data["last_winner"]:
            w = data["last_winner"]
            embed.add_field(name="🚩 Last winner", value=f"{team_label(w)} ({w['season_id']})", inline=True)
        if data["team"]:
            mine = f"#{data['rank']} — {em(data['score'])}" if data["rank"] else "Not ranked yet"
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


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamsCog(bot))
