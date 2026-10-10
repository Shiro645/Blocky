from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import moderation
from game.errors import GameError
from game.moderation import format_duration
from utils.checks import is_staff, staff_only
from utils.config import staff_role_id
from utils.ui import join_lines

log = logging.getLogger("moderation")

ICONS = {"warn": "⚠️", "mute": "🔇", "kick": "👢", "ban": "🔨"}
DURATION_HELP = "e.g. 30m, 2h, 3d, 1w, or perm"
DELETE_CHOICES = [
    app_commands.Choice(name="Don't delete messages", value=0),
    app_commands.Choice(name="Last hour", value=3600),
    app_commands.Choice(name="Last 24 hours", value=86400),
    app_commands.Choice(name="Last 7 days", value=604800),
]
Reason = app_commands.Range[str, 1, 400]


def stamp(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc)


def check_target(interaction: discord.Interaction, target: discord.abc.User) -> None:
    """Refuse sanctions on oneself, bots, the owner, staff, or members above the moderator or the bot."""
    guild = interaction.guild
    if guild is None:
        raise GameError("This command only works on the server.")
    if target.id == interaction.user.id:
        raise GameError("You can't sanction yourself.")
    if target.bot:
        raise GameError("You can't sanction a bot.")
    if target.id == guild.owner_id:
        raise GameError("You can't sanction the server owner.")
    if not isinstance(target, discord.Member):
        return
    if is_staff(target):
        raise GameError("You can't sanction a staff member.")
    if target.top_role >= guild.me.top_role:
        raise GameError(f"{target.mention}'s highest role is above mine: move my role higher in the server settings.")
    moderator = interaction.user
    if isinstance(moderator, discord.Member) and moderator.id != guild.owner_id and target.top_role >= moderator.top_role:
        raise GameError(f"{target.mention}'s highest role is not below yours.")


class ModerationCog(commands.Cog):
    """Staff moderation: warnings, mutes (Discord timeouts), kicks, bans, clear, lock, slowmode."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.moderation_loop.start()

    async def cog_unload(self) -> None:
        self.moderation_loop.cancel()

    # ---------- helpers ----------
    async def notify(self, user: discord.abc.User, guild: discord.Guild, text: str, reason: str | None) -> bool:
        """DM the member (best effort: DMs can be closed). Returns True if it was delivered."""
        try:
            await user.send(f"{text} on **{guild.name}**." + (f"\nReason: {reason}" if reason else ""))
            return True
        except discord.HTTPException:
            return False

    async def log_action(self, title: str, target: discord.abc.User | int, moderator: discord.abc.User | None,
                         reason: str | None, color: discord.Color, extra: str | None = None) -> None:
        who = f"<@{target}> (`{target}`)" if isinstance(target, int) else f"{target.mention} (`{target}`)"
        embed = discord.Embed(title=title, color=color)
        embed.add_field(name="Member", value=who, inline=True)
        embed.add_field(name="By", value=moderator.mention if moderator else "Blocky (automatic)", inline=True)
        if extra:
            embed.add_field(name="Details", value=extra, inline=False)
        embed.add_field(name="Reason", value=reason or "—", inline=False)
        await self.bot.announcer.send(embed=embed, channel="staff_log")

    async def apply_mute(self, member: discord.Member, sanction: dict) -> None:
        """Set the Discord timeout of a mute (28 days at most: renewed later by the loop)."""
        until = await self.bot.db.run(moderation.timeout_until, sanction)
        await member.timeout(stamp(until), reason=sanction["reason"] or "Blocky mute")
        await self.bot.db.run(moderation.set_applied, sanction["sanction_id"], until)

    async def mute_member(self, interaction: discord.Interaction | None, member: discord.Member, duration: int | None,
                          reason: str | None, moderator: discord.abc.User | None) -> dict:
        moderator_id = moderator.id if moderator else self.bot.user.id
        sanction = await self.bot.db.run(moderation.add, member.id, "mute", reason, moderator_id, duration)
        try:
            await self.apply_mute(member, sanction)
        except discord.HTTPException:
            # Discord refused (missing permission, admin member...): don't keep a mute that isn't applied.
            await self.bot.db.run(moderation.lift, member.id, "mute", moderator_id)
            raise
        length = format_duration(duration)
        dm = await self.notify(member, member.guild, f"🔇 You have been muted ({length})", reason)
        await self.log_action(
            f"🔇 Mute ({length})", member, moderator, reason, discord.Color.orange(),
            None if dm else "Could not DM the member.",
        )
        return sanction

    # ---------- clock ----------
    @tasks.loop(minutes=10)
    async def moderation_loop(self):
        try:
            await self.moderation_tick()
        except Exception:  # an error must never stop the loop
            log.exception("Moderation loop failed")

    @moderation_loop.before_loop
    async def before_moderation_loop(self):
        await self.bot.wait_until_ready()

    async def moderation_tick(self) -> None:
        guild = self.bot.main_guild
        if guild is None:
            return
        due = await self.bot.db.run(moderation.due)
        for ban in due["unban"]:
            try:
                await guild.unban(discord.Object(ban["user_id"]), reason="Blocky: temporary ban ended")
            except discord.NotFound:
                pass  # already unbanned by hand
            except discord.HTTPException:
                log.exception("Could not unban %s", ban["user_id"])
                continue
            await self.log_action("🔓 Temporary ban ended", ban["user_id"], None, ban["reason"], discord.Color.green())
        for mute in due["unmuted"]:
            await self.log_action("🔊 Mute ended", mute["user_id"], None, mute["reason"], discord.Color.green())
        for mute in due["renew"]:
            member = guild.get_member(mute["user_id"])
            if member is None:
                continue  # left the server: re-applied if they come back (on_member_join)
            try:
                await self.apply_mute(member, mute)
            except discord.HTTPException:
                log.exception("Could not renew the mute of %s", mute["user_id"])

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Leaving and rejoining doesn't end a mute."""
        if member.guild != self.bot.main_guild:
            return
        mute = await self.bot.db.run(moderation.active, member.id, "mute")
        if mute is None or (mute["expires_at"] is not None and mute["expires_at"] <= datetime.now().timestamp()):
            return
        try:
            await self.apply_mute(member, mute)
        except discord.HTTPException:
            log.exception("Could not re-apply the mute of %s", member.id)

    # ---------- warnings ----------
    @app_commands.command(name="warn", description="STAFF: Warn a member (automatic mute after several warnings).")
    @app_commands.describe(member="Who to warn", reason="Why (sent to the member)")
    @staff_only()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: Reason):
        check_target(interaction, member)
        await interaction.response.defer(ephemeral=True, thinking=True)
        res = await self.bot.db.run(moderation.warn, member.id, reason, interaction.user.id)
        count = res["count"]
        dm = await self.notify(member, interaction.guild, f"⚠️ You received a warning ({count} active)", reason)
        await self.log_action(
            f"⚠️ Warning #{res['sanction']['sanction_id']} ({count} active)", member, interaction.user, reason,
            discord.Color.gold(), None if dm else "Could not DM the member.",
        )
        text = f"⚠️ {member.mention} warned ({count} active warning{'s' if count > 1 else ''})."
        if res["auto_mute"]:
            await self.mute_member(None, member, res["auto_mute"], f"Automatic: {count} warnings", None)
            text += f"\n🔇 Automatic mute: **{format_duration(res['auto_mute'])}**."
        await interaction.followup.send(text, ephemeral=True)

    @app_commands.command(name="unwarn", description="STAFF: Remove a warning (its # is shown in /history).")
    @app_commands.describe(warning="Warning number, e.g. 12")
    @staff_only()
    async def unwarn(self, interaction: discord.Interaction, warning: app_commands.Range[int, 1]):
        row = await self.bot.db.run(moderation.remove_warn, warning, interaction.user.id)
        await interaction.response.send_message(f"✅ Warning `#{warning}` of <@{row['user_id']}> removed.", ephemeral=True)
        await self.log_action(f"🧽 Warning #{warning} removed", row["user_id"], interaction.user, row["reason"], discord.Color.light_grey())

    @app_commands.command(name="clearwarns", description="STAFF: Remove all the warnings of a member.")
    @staff_only()
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        n = await self.bot.db.run(moderation.clear_warns, member.id, interaction.user.id)
        await interaction.response.send_message(f"✅ {n} warning(s) of {member.mention} removed.", ephemeral=True)
        await self.log_action(f"🧽 {n} warning(s) cleared", member, interaction.user, None, discord.Color.light_grey())

    @app_commands.command(name="history", description="STAFF: A member's warnings and sanctions.")
    @staff_only()
    async def history(self, interaction: discord.Interaction, member: discord.User):
        h = await self.bot.db.run(moderation.history, member.id)
        lines = []
        for r in h["rows"]:
            line = f"`#{r['sanction_id']}` {ICONS.get(r['kind'], '•')} **{r['kind']}**"
            if r["kind"] in ("mute", "ban"):
                length = None if r["expires_at"] is None else r["expires_at"] - r["created_at"]
                line += f" ({format_duration(length)})"
            line += f" <t:{r['created_at']}:d> by <@{r['moderator_id']}>"
            if r["kind"] in ("mute", "ban", "warn") and not r["active"]:
                line += " — *removed*" if r["kind"] == "warn" else " — *ended*"
            if r["reason"]:
                line += f"\n  └ {r['reason'][:150]}"
            lines.append(line)
        embed = discord.Embed(
            title=f"📋 History of {member}",
            description=join_lines(lines, limit=3800, empty="Nothing on record. ✨"),
            color=discord.Color.blurple(),
        )
        status = [f"⚠️ {h['warns']} active warning(s)"]
        if h["mute"]:
            end = "permanent" if h["mute"]["expires_at"] is None else f"until <t:{h['mute']['expires_at']}:f>"
            status.append(f"🔇 Muted ({end})")
        if h["ban"]:
            end = "permanent" if h["ban"]["expires_at"] is None else f"until <t:{h['ban']['expires_at']}:f>"
            status.append(f"🔨 Banned ({end})")
        embed.add_field(name="Now", value="\n".join(status), inline=False)
        embed.set_footer(text=f"{h['total']} record(s) · /unwarn <#> to remove a warning")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------- mute ----------
    @app_commands.command(name="mute", description="STAFF: Mute a member (temporary or permanent).")
    @app_commands.describe(member="Who to mute", duration=DURATION_HELP, reason="Why (sent to the member)")
    @staff_only()
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: Reason):
        check_target(interaction, member)
        seconds = moderation.parse_duration(duration)
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.mute_member(interaction, member, seconds, reason, interaction.user)
        await interaction.followup.send(f"🔇 {member.mention} is muted ({format_duration(seconds)}).", ephemeral=True)

    @app_commands.command(name="unmute", description="STAFF: End a member's mute.")
    @staff_only()
    async def unmute(self, interaction: discord.Interaction, member: discord.Member, reason: Reason | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        ended = await self.bot.db.run(moderation.lift, member.id, "mute", interaction.user.id)
        if not ended and not member.is_timed_out():
            raise GameError(f"{member.mention} isn't muted.")
        await member.timeout(None, reason=reason or "Blocky unmute")
        await self.notify(member, interaction.guild, "🔊 Your mute was lifted", reason)
        await self.log_action("🔊 Unmute", member, interaction.user, reason, discord.Color.green())
        await interaction.followup.send(f"🔊 {member.mention} can talk again.", ephemeral=True)

    # ---------- kick and ban ----------
    @app_commands.command(name="kick", description="STAFF: Kick a member (they can come back with an invite).")
    @staff_only()
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: Reason):
        check_target(interaction, member)
        await interaction.response.defer(ephemeral=True, thinking=True)
        # DM first: once kicked, the bot can't reach them anymore.
        dm = await self.notify(member, interaction.guild, "👢 You have been kicked", reason)
        await member.kick(reason=reason)
        await self.bot.db.run(moderation.add, member.id, "kick", reason, interaction.user.id)
        await self.log_action("👢 Kick", member, interaction.user, reason, discord.Color.red(), None if dm else "Could not DM the member.")
        await interaction.followup.send(f"👢 {member.mention} was kicked.", ephemeral=True)

    @app_commands.command(name="ban", description="STAFF: Ban a member (temporary or permanent).")
    @app_commands.describe(
        member="Who to ban", reason="Why (sent to the member)", duration=f"{DURATION_HELP} (perm by default)",
        delete_messages="Also delete their recent messages",
    )
    @app_commands.choices(delete_messages=DELETE_CHOICES)
    @staff_only()
    async def ban(
        self, interaction: discord.Interaction, member: discord.User, reason: Reason,
        duration: str = "perm", delete_messages: int = 0,
    ):
        target = interaction.guild.get_member(member.id) if interaction.guild else None
        check_target(interaction, target or member)
        seconds = moderation.parse_duration(duration)
        length = format_duration(seconds)
        await interaction.response.defer(ephemeral=True, thinking=True)
        dm = False
        if target is not None:
            until = f" (until <t:{int(datetime.now().timestamp()) + seconds}:f>)" if seconds else ""
            dm = await self.notify(target, interaction.guild, f"🔨 You have been banned ({length}){until}", reason)
        await interaction.guild.ban(member, reason=reason, delete_message_seconds=delete_messages)
        await self.bot.db.run(moderation.add, member.id, "ban", reason, interaction.user.id, seconds)
        await self.log_action(
            f"🔨 Ban ({length})", member, interaction.user, reason, discord.Color.dark_red(),
            None if dm or target is None else "Could not DM the member.",
        )
        await interaction.followup.send(f"🔨 {member.mention} is banned ({length}).", ephemeral=True)

    @app_commands.command(name="unban", description="STAFF: Lift a ban (use the user ID shown in /history or the logs).")
    @app_commands.describe(user_id="The banned user's ID")
    @staff_only()
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: Reason | None = None):
        try:
            uid = int(user_id.strip().strip("<@!>"))
        except ValueError:
            raise GameError("Give the user's ID (a number), e.g. 123456789012345678.")
        try:
            await interaction.guild.unban(discord.Object(uid), reason=reason or "Blocky unban")
        except discord.NotFound:
            await self.bot.db.run(moderation.lift, uid, "ban", interaction.user.id)
            raise GameError(f"<@{uid}> isn't banned.")
        await self.bot.db.run(moderation.lift, uid, "ban", interaction.user.id)
        await interaction.response.send_message(f"🔓 <@{uid}> is unbanned.", ephemeral=True)
        await self.log_action("🔓 Unban", uid, interaction.user, reason, discord.Color.green())

    # ---------- channels ----------
    @app_commands.command(name="clear", description="STAFF: Delete the last messages of this channel (pinned ones are kept).")
    @app_commands.describe(amount="How many messages (1-100)", member="Only this member's messages")
    @staff_only()
    async def clear(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100], member: discord.User | None = None):
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            raise GameError("This only works in a text channel.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        matched = 0

        def check(msg: discord.Message) -> bool:
            nonlocal matched
            if msg.pinned or (member is not None and msg.author.id != member.id) or matched >= amount:
                return False
            matched += 1
            return True

        # With a member filter, look further back to find enough of their messages.
        deleted = await channel.purge(limit=amount if member is None else 500, check=check, reason=f"/clear by {interaction.user}")
        who = f" from {member.mention}" if member else ""
        await self.log_action(
            f"🧹 {len(deleted)} message(s) deleted", member.id if member else interaction.user, interaction.user, None,
            discord.Color.light_grey(), f"In {channel.mention}{who}",
        )
        await interaction.followup.send(f"🧹 {len(deleted)} message(s){who} deleted.", ephemeral=True)

    async def set_lock(self, interaction: discord.Interaction, channel: discord.TextChannel, locked: bool, reason: str | None) -> None:
        guild = interaction.guild
        everyone = channel.overwrites_for(guild.default_role)
        everyone.send_messages = False if locked else None
        everyone.send_messages_in_threads = False if locked else None
        await channel.set_permissions(guild.default_role, overwrite=everyone, reason=reason or f"/lock by {interaction.user}")
        staff = guild.get_role(staff_role_id())
        if staff is not None:
            # Staff can still talk in a locked channel.
            allowed = channel.overwrites_for(staff)
            allowed.send_messages = True if locked else None
            await channel.set_permissions(staff, overwrite=allowed, reason="Staff can talk in locked channels")

    @app_commands.command(name="lock", description="STAFF: Nobody (except staff) can write in a channel anymore.")
    @app_commands.describe(channel="This channel by default", reason="Shown in the channel")
    @staff_only()
    async def lock(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None, reason: Reason | None = None):
        channel = channel or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            raise GameError("Pick a text channel.")
        await self.set_lock(interaction, channel, True, reason)
        await interaction.response.send_message(f"🔒 {channel.mention} is locked.", ephemeral=True)
        await channel.send("🔒 This channel is locked." + (f" Reason: {reason}" if reason else ""))
        await self.log_action("🔒 Channel locked", interaction.user, interaction.user, reason, discord.Color.dark_grey(), channel.mention)

    @app_commands.command(name="unlock", description="STAFF: Let members write in a locked channel again.")
    @staff_only()
    async def unlock(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None):
        channel = channel or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            raise GameError("Pick a text channel.")
        await self.set_lock(interaction, channel, False, f"/unlock by {interaction.user}")
        await interaction.response.send_message(f"🔓 {channel.mention} is unlocked.", ephemeral=True)
        await channel.send("🔓 This channel is open again.")
        await self.log_action("🔓 Channel unlocked", interaction.user, interaction.user, None, discord.Color.dark_grey(), channel.mention)

    @app_commands.command(name="slowmode", description="STAFF: Set the slow mode of a channel (0 = off).")
    @app_commands.describe(seconds="Seconds between two messages of a member (0-21600)", channel="This channel by default")
    @staff_only()
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600], channel: discord.TextChannel | None = None):
        channel = channel or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            raise GameError("Pick a text channel.")
        await channel.edit(slowmode_delay=seconds, reason=f"/slowmode by {interaction.user}")
        text = f"🐢 Slow mode in {channel.mention}: **{seconds}s**." if seconds else f"🐇 Slow mode off in {channel.mention}."
        await interaction.response.send_message(text, ephemeral=True)
        await self.log_action("🐢 Slow mode", interaction.user, interaction.user, None, discord.Color.dark_grey(), text)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCog(bot))
