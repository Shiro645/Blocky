from __future__ import annotations

import asyncio
import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import events, settings
from game.errors import GameError
from utils.checks import staff_only
from utils.config import role_id
from utils.ui import em, progress_bar, report_error

log = logging.getLogger("boss")

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
HOUR = 3600


def boss_embed(boss: dict) -> discord.Embed:
    status = boss["status"]
    if status == "defeated":
        title, color = f"💀 {boss['name']} has been defeated!", discord.Color.green()
    elif status == "escaped":
        title, color = f"💨 {boss['name']} escaped…", discord.Color.dark_grey()
    else:
        title, color = f"🐉 {boss['name']} attacks the server!", discord.Color.dark_red()

    desc = f"`{progress_bar(boss['hp'], boss['max_hp'], 20)}`\n**{boss['hp']:,} / {boss['max_hp']:,} HP**"
    if status == "active":
        desc += (
            f"\n\nEveryone can attack once every {settings.get()['boss']['attack_cooldown_seconds']}s "
            f"with the button or `/attack`. Your sword makes the difference!\nEscapes <t:{boss['ends_at']}:R>."
        )
    embed = discord.Embed(title=title, description=desc, color=color)
    top = boss.get("ranking", [])[:5]
    if top:
        embed.add_field(
            name="Top damage",
            value="\n".join(
                f"{MEDALS.get(i, f'`#{i}`')} <@{r['user_id']}> — {r['damage']:,} ({r['hits']} hits)"
                for i, r in enumerate(top, start=1)
            ),
            inline=False,
        )
    return embed


class BossAttackButton(discord.ui.DynamicItem[discord.ui.Button], template=r"blocky:boss:(?P<boss_id>\d+)"):
    """Attack button that keeps working after a bot restart."""

    def __init__(self, boss_id: int, disabled: bool = False) -> None:
        super().__init__(
            discord.ui.Button(
                label="Attack!", style=discord.ButtonStyle.danger, emoji="⚔️",
                custom_id=f"blocky:boss:{boss_id}", disabled=disabled,
            )
        )
        self.boss_id = boss_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["boss_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: BossCog | None = interaction.client.get_cog("BossCog")  # type: ignore[assignment]
        if cog is None:
            return
        try:
            await cog.attack(interaction, self.boss_id)
        except Exception as error:
            await report_error(interaction, error)


def boss_view(boss_id: int, active: bool) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(BossAttackButton(boss_id, disabled=not active))
    return view


class BossCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._refresh_scheduled: set[int] = set()
        self._post_retry_at = 0.0
        self._posting: set[int] = set()  # bosses being posted
        self._tasks: set[asyncio.Task] = set()

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(BossAttackButton)
        self.boss_loop.start()

    async def cog_unload(self) -> None:
        self.boss_loop.cancel()
        self.bot.remove_dynamic_items(BossAttackButton)

    # ---------- boss message ----------
    async def post_boss(self, boss: dict, channel: discord.abc.Messageable) -> None:
        # /boss_spawn and the loop can both try to post a new boss: only one does.
        if boss["boss_id"] in self._posting:
            return
        self._posting.add(boss["boss_id"])
        try:
            fresh = await self.bot.db.run(events.get_boss, boss["boss_id"])
            if fresh is None or fresh["message_id"]:
                return  # already posted
            boss["ranking"] = []
            ping = role_id("event_ping")
            msg = await channel.send(
                content=f"<@&{ping}>" if ping else None,
                embed=boss_embed(boss),
                view=boss_view(boss["boss_id"], True),
                # Only the configured role is pinged, never @everyone / @here.
                allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=[discord.Object(ping)] if ping else False),
            )
            await self.bot.db.run(events.set_boss_message, boss["boss_id"], msg.channel.id, msg.id)
        finally:
            self._posting.discard(boss["boss_id"])

    async def refresh_message(self, boss_id: int) -> None:
        data = await self.bot.db.run(events.boss_view, boss_id)
        if not data or not data["channel_id"] or not data["message_id"]:
            return
        channel = self.bot.get_channel(data["channel_id"])
        if not isinstance(channel, discord.abc.Messageable):
            return
        try:
            msg = channel.get_partial_message(data["message_id"])  # type: ignore[attr-defined]
            await msg.edit(embed=boss_embed(data), view=boss_view(boss_id, data["status"] == "active"))
        except discord.HTTPException:
            log.warning("Could not update boss message %s", data["message_id"])

    def schedule_refresh(self, boss_id: int) -> None:
        """Update the boss message at most every few seconds (Discord rate limits edits)."""
        if boss_id in self._refresh_scheduled:
            return
        self._refresh_scheduled.add(boss_id)

        async def later():
            await asyncio.sleep(3)
            self._refresh_scheduled.discard(boss_id)
            await self.refresh_message(boss_id)

        task = asyncio.create_task(later())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---------- attacking ----------
    async def attack(self, interaction: discord.Interaction, boss_id: int | None = None) -> None:
        res = await self.bot.db.run(events.attack_boss, interaction.user.id, boss_id)
        crit = "💥 **Critical hit!** " if res["crit"] else ""
        text = f"{crit}You dealt **{res['damage']}** damage to {res['name']} ({max(0, res['hp'])}/{res['max_hp']} HP left)."
        if res["sword_broke"]:
            text += "\n🔨 Your sword broke!"
        await interaction.response.send_message(text, ephemeral=True)

        if res["defeat"]:
            await self.refresh_message(res["boss_id"])
            await self.announce_defeat(res)
        else:
            self.schedule_refresh(res["boss_id"])

    async def announce_defeat(self, res: dict) -> None:
        lines = []
        for i, r in enumerate(res["defeat"]["rewards"][:10], start=1):
            line = f"{MEDALS.get(i, f'`#{i}`')} <@{r['user_id']}> — {r['damage']:,} damage → **+{em(r['reward'])}**"
            if r.get("looting"):
                line += f" (Looting +{r['looting']:,})"
            if r.get("book"):
                line += f" + 📕 **{r['book']}** book"
            lines.append(line)
        embed = discord.Embed(
            title=f"💀 {res['name']} has been defeated!",
            description="\n".join(lines) + f"\n\nEvery fighter also earned **{res['defeat']['xp']} XP**.",
            color=discord.Color.green(),
        )
        await self.bot.announcer.send(embed=embed)

    @app_commands.command(name="attack", description="Attack the current boss.")
    async def attack_cmd(self, interaction: discord.Interaction):
        await self.attack(interaction)

    @app_commands.command(name="boss", description="Show the current boss.")
    async def boss_cmd(self, interaction: discord.Interaction):
        def load(ctx):
            boss = events.active_boss(ctx)
            return events.boss_view(ctx, boss["boss_id"]) if boss else None

        data = await self.bot.db.run(load)
        if data is None:
            raise GameError("No boss right now. Stay tuned!")
        await interaction.response.send_message(embed=boss_embed(data), view=boss_view(data["boss_id"], True), ephemeral=True)

    @app_commands.command(name="boss_spawn", description="STAFF: Summon a boss.")
    @app_commands.describe(name="Boss name (random if empty)", hp="Health points (default from settings)")
    @staff_only()
    async def boss_spawn(
        self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 64] | None = None,
        hp: app_commands.Range[int, 1, 10_000_000] | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        boss = await self.bot.db.run(events.spawn_boss, name, hp)
        channel = self.bot.announcer.channel("events") or interaction.channel
        # If posting fails (permissions), the boss stays and the loop posts it later.
        await self.post_boss(boss, channel)
        await interaction.followup.send(f"✅ {boss['name']} summoned in {channel.mention}.", ephemeral=True)

    # ---------- background ----------
    @tasks.loop(minutes=1)
    async def boss_loop(self):
        try:
            await self.boss_tick()
        except Exception:  # an error must never stop the loop
            log.exception("Boss loop failed")

    async def boss_tick(self) -> None:
        escaped = await self.bot.db.run(events.escape_expired)
        for boss in escaped:
            await self.refresh_message(boss["boss_id"])
            await self.bot.announcer.send(f"💨 **{boss['name']}** escaped… Better luck next time!")

        channel = self.bot.announcer.channel("events") or self.bot.announcer.channel()
        if channel is None or time.monotonic() < self._post_retry_at:
            return

        interval = float(settings.get()["boss"]["auto_spawn_hours"])

        def pending_or_spawn(ctx):
            boss = events.active_boss(ctx)
            if boss:
                # A boss whose message could not be posted yet (e.g. missing permission).
                return boss if not boss["message_id"] else None
            if interval > 0 and ctx.now >= events.last_boss_end(ctx) + interval * HOUR:
                return events.spawn_boss(ctx)
            return None

        boss = await self.bot.db.run(pending_or_spawn)
        if boss is None:
            return
        try:
            await self.post_boss(boss, channel)
        except discord.HTTPException:
            self._post_retry_at = time.monotonic() + 600
            log.warning(
                "Could not post boss %s in #%s: give the bot View Channel, Send Messages and "
                "Embed Links there. Retrying in 10 minutes.", boss["name"], getattr(channel, "name", "?"),
            )

    @boss_loop.before_loop
    async def before_boss_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(BossCog(bot))
