from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import live_events, settings
from utils.config import role_id

log = logging.getLogger("live_events")


def event_embed(event: dict, ended: bool = False) -> discord.Embed:
    kind = live_events.KINDS[event["kind"]]
    if ended:
        return discord.Embed(title=f"{kind.label} is over", description=f"~~{live_events.describe(event['kind'])}~~\n"
                             "See you at the next event!", color=discord.Color.dark_grey())
    return discord.Embed(
        title=f"{kind.label} has started!",
        description=f"**{live_events.describe(event['kind'])}** for everyone.\nEnds <t:{event['ends_at']}:R> "
                    f"(<t:{event['ends_at']}:t>).",
        color=discord.Color.gold(),
    )


class LiveEventsCog(commands.Cog):
    """Timed events: their announcements, the daily random one and /events."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lock = asyncio.Lock()  # the loop and the staff commands: one sync at a time (no double post)

    async def cog_load(self) -> None:
        self.events_loop.start()

    async def cog_unload(self) -> None:
        self.events_loop.cancel()

    @tasks.loop(minutes=1)
    async def events_loop(self):
        try:
            await self.sync()
        except Exception:  # an error must never stop the loop
            log.exception("Timed events loop failed")

    @events_loop.before_loop
    async def before_events_loop(self):
        await self.bot.wait_until_ready()

    async def sync(self) -> None:
        """Start the day's random event, post the new ones, mark the ended ones."""
        async with self._lock:
            changed = await self._sync()
        if changed:
            self.bot.dispatch("blocky_live_event")  # e.g. the market board shows the Market Sale prices

    async def _sync(self) -> bool:
        changed = False
        for change in await self.bot.db.run(live_events.tick):
            changed = True
            if change["type"] == "ended":
                await self.show_end(change["event"])
        for event in await self.bot.db.run(live_events.to_announce):
            changed = True
            await self.post(event)
        return changed

    async def post(self, event: dict) -> None:
        channel = self.bot.announcer.channel("events") or self.bot.announcer.channel()
        message = None
        if channel is not None:
            rid = role_id("event_ping")
            try:
                message = await channel.send(
                    content=f"<@&{rid}>" if rid else None, embed=event_embed(event),
                    # Only the configured role is pinged, never @everyone / @here.
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False, users=False, roles=[discord.Object(rid)] if rid else False),
                )
            except discord.HTTPException:
                log.warning("Could not announce the timed event", exc_info=True)
        # Marked as posted even without a channel: the event still runs, only its message is missing.
        await self.bot.db.run(live_events.set_message, event["event_id"],
                              message.channel.id if message else None, message.id if message else None)

    async def show_end(self, event: dict) -> None:
        channel = self.bot.get_channel(event["channel_id"]) if event["channel_id"] else None
        if not isinstance(channel, discord.abc.Messageable) or not event["message_id"]:
            return
        try:
            await channel.get_partial_message(event["message_id"]).edit(content=None, embed=event_embed(event, ended=True))
        except discord.HTTPException:
            log.warning("Could not update the timed event message", exc_info=True)

    # ---------- commands ----------
    @app_commands.command(name="events", description="The timed event on now, and what each event does.")
    async def events_cmd(self, interaction: discord.Interaction):
        event = await self.bot.db.run(live_events.current)
        c = settings.get()["live_events"]
        if event:
            kind = live_events.KINDS[event["kind"]]
            head = (f"**{kind.label}** is on: {live_events.describe(event['kind'])}. Ends <t:{event['ends_at']}:R>.")
        else:
            head = "No event is on right now."
        if c["daily_random"] and live_events.random_kinds():
            head += (f"\nOne event comes by itself every day, at a random time between "
                     f"**{int(c['earliest_hour']):02d}:00** and **{int(c['latest_hour']):02d}:00**, for "
                     f"**{int(c['duration_minutes'])} min**.")
        embed = discord.Embed(title="⏱️ Timed events", description=head, color=discord.Color.gold())
        for key, kind in live_events.KINDS.items():
            embed.add_field(name=kind.label, value=live_events.describe(key), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def staff_start(self, interaction: discord.Interaction, kind: str, minutes: int | None) -> None:
        """/event start (cogs/staff_events.py)."""
        event = await self.bot.db.run(live_events.start, kind, minutes, interaction.user.id)
        await interaction.response.send_message(
            f"✅ **{live_events.KINDS[kind].label}** started, until <t:{event['ends_at']}:t>.", ephemeral=True)
        await self.sync()

    async def staff_stop(self, interaction: discord.Interaction) -> None:
        """/event stop (cogs/staff_events.py)."""
        event = await self.bot.db.run(live_events.stop)
        await interaction.response.send_message(f"✅ **{live_events.KINDS[event['kind']].label}** ended.", ephemeral=True)
        await self.sync()


async def setup(bot: commands.Bot):
    await bot.add_cog(LiveEventsCog(bot))
