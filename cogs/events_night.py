from __future__ import annotations

import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import night, pve, settings
from utils.ui import em, join_lines, report_error

log = logging.getLogger("night")
SEEN_EVERY = 600  # seconds: a player's activity is written at most this often

COLORS = {"waiting": discord.Color.dark_purple(), "won": discord.Color.green(), "lost": discord.Color.dark_red(),
          "fled": discord.Color.dark_grey()}


def monster_label(kind: str) -> str:
    k = pve.MONSTERS[kind]
    return f"{k.emoji} {k.name}"


def attack_embed(a: dict) -> discord.Embed:
    c = settings.get()["night"]
    name, who = monster_label(a["kind"]), f"<@{a['target_id']}>"
    if a["status"] == "waiting":
        phantom = a["kind"] == night.PHANTOM
        share, top = (c["phantom_loss"], c["phantom_loss_max"]) if phantom else (c["loss"], c["loss_max"])
        why = " It hunts the ones who don't sleep…" if phantom else ""
        text = (f"🌙 A **{name}** attacks {who}!{why}\nFight it before <t:{a['deadline']}:t> (<t:{a['deadline']}:R>): "
                f"beat it for {em(night.reward(a['kind']))} and {c['xp']} XP. Lose, or let it be, and it takes "
                f"{float(share):.0%} of your emeralds ({em(int(top))} at most).\n"
                "*Sleep with `/sleep` at night and no monster comes for you.*")
    elif a["status"] == "won":
        text = "\n".join(a["log"]) + f"\n\n🏆 {who} beat the **{name}**: +{em(a['amount'])}!"
    elif a["status"] == "lost":
        text = ("\n".join(a["log"]) + f"\n\n☠️ The **{name}** beat {who}"
                + (f" and took {em(a['amount'])}." if a["amount"] else "."))
    else:
        text = f"💨 {who} never came: the **{name}** left" + (f" with {em(a['amount'])}." if a["amount"] else ".")
    return discord.Embed(title=f"{name} in the night", description=join_lines(text.split("\n"), 4000),
                         color=COLORS.get(a["status"]))


class FightButton(discord.ui.DynamicItem[discord.ui.Button], template=r"blocky:night:fight:(?P<attack_id>\d+)"):
    """The Fight button of a night monster. It survives restarts."""

    def __init__(self, attack_id: int) -> None:
        super().__init__(discord.ui.Button(label="Fight", emoji="⚔️", style=discord.ButtonStyle.danger,
                                           custom_id=f"blocky:night:fight:{attack_id}"))
        self.attack_id = attack_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["attack_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            a = await interaction.client.db.run(night.fight, self.attack_id, interaction.user.id)  # type: ignore[attr-defined]
            await interaction.response.edit_message(embed=attack_embed(a), view=None)
        except Exception as error:
            await report_error(interaction, error)


def fight_view(attack_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(FightButton(attack_id))
    return view


class NightCog(commands.Cog):
    """/time, /sleep and /wake: day and night, and the monsters of the night."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._seen: dict[int, float] = {}  # user -> when their activity was last written (monotonic)

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(FightButton)
        self.night_loop.start()

    async def cog_unload(self) -> None:
        self.night_loop.cancel()
        self.bot.remove_dynamic_items(FightButton)

    @app_commands.command(name="time", description="Day or night? When it changes, and whether you slept.")
    async def time_cmd(self, interaction: discord.Interaction):
        st = await self.bot.db.run(night.status, interaction.user.id)
        c = settings.get()["night"]
        if st["night"]:
            lines = [f"🌙 **It's night.** The sun rises <t:{st['change']}:R> (<t:{st['change']}:t>)."]
            if st["slept"]:
                lines.append("💤 You're asleep: no monster comes for you, and tomorrow's `/daily` pays "
                             f"+{float(c['sleep_daily_bonus']):.0%}. Only the commands that look things up "
                             "work until dawn (`/wake` to get up).")
            elif st.get("woke"):
                lines.append("👀 You got up tonight: monsters may attack you, and no going back to bed.")
            else:
                lines.append(f"👀 You're awake: monsters may attack you. `/sleep` to be safe (and +"
                             f"{float(c['sleep_daily_bonus']):.0%} on tomorrow's `/daily`).")
                if st["awake"] >= int(c["phantom_nights"]):
                    lines.append(f"👻 You haven't slept for {st['awake']} nights: Phantoms are after you!")
        else:
            lines = [f"☀️ **It's day.** The sun sets <t:{st['change']}:R> (<t:{st['change']}:t>)."]
            if st.get("rested"):
                lines.append(f"🛏️ You slept last night: today's `/daily` pays +{float(c['sleep_daily_bonus']):.0%}.")
        if st["waiting"]:
            a = st["waiting"]
            lines.append(f"⚔️ A **{monster_label(a['kind'])}** is attacking you: fight it before <t:{a['deadline']}:t>!")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="sleep", description="Go to bed (at night): no monster attacks you, and a bigger /daily.")
    async def sleep(self, interaction: discord.Interaction):
        res = await self.bot.db.run(night.sleep, interaction.user.id)
        await interaction.response.send_message(
            f"💤 Good night! No monster comes for you until <t:{res['dawn']}:t>, and your next `/daily` pays "
            f"+{res['bonus']:.0%}.", ephemeral=True)

    @app_commands.command(name="wake", description="Get up before dawn: monsters can attack you again, no /daily bonus.")
    async def wake(self, interaction: discord.Interaction):
        res = await self.bot.db.run(night.wake, interaction.user.id)
        await interaction.response.send_message(
            f"☀️ You're up. Monsters may attack you until <t:{res['dawn']}:t>, your next `/daily` has no "
            f"+{res['bonus']:.0%}, and you can't go back to bed tonight.", ephemeral=True)

    # ---------- activity (only active players are attacked) ----------
    async def note(self, user_id: int) -> None:
        now = time.monotonic()
        if now - self._seen.get(user_id, -SEEN_EVERY) < SEEN_EVERY:
            return
        self._seen[user_id] = now
        try:
            await self.bot.db.run(night.seen, user_id)
        except Exception:
            log.debug("Could not note an activity", exc_info=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if not interaction.user.bot:
            await self.note(interaction.user.id)

    @commands.Cog.listener()
    async def on_blocky_mined(self, message: discord.Message, result: dict) -> None:
        await self.note(message.author.id)

    # ---------- background ----------
    def candidates(self) -> list[int]:
        guild = getattr(self.bot, "main_guild", None)
        return [m.id for m in guild.members if not m.bot] if guild else []

    def channel(self) -> discord.abc.Messageable | None:
        return self.bot.announcer.channel("events") or self.bot.announcer.channel()

    async def post(self, a: dict) -> None:
        channel = self.channel()
        if channel is None:
            await self.bot.db.run(night.unposted, a["attack_id"])  # no fight button anywhere: no attack
            return
        try:
            message = await channel.send(
                f"<@{a['target_id']}>", embed=attack_embed(a), view=fight_view(a["attack_id"]),
                allowed_mentions=discord.AllowedMentions(users=[discord.Object(a["target_id"])]),
            )
            await self.bot.db.run(night.set_message, a["attack_id"], message.channel.id, message.id)
        except discord.HTTPException:
            log.warning("Could not post a night monster", exc_info=True)
            await self.bot.db.run(night.unposted, a["attack_id"])

    async def refresh(self, a: dict) -> None:
        channel = self.bot.get_channel(a["channel_id"] or 0)
        if not isinstance(channel, discord.abc.Messageable) or not a["message_id"]:
            return
        try:
            await channel.get_partial_message(a["message_id"]).edit(embed=attack_embed(a), view=None)
        except discord.HTTPException:
            log.warning("Could not update a night monster", exc_info=True)

    @tasks.loop(minutes=1)
    async def night_loop(self):
        try:
            change = await self.bot.db.run(night.to_announce)
            if change == "dusk":
                await self.bot.announcer.send(
                    "🌙 **The sun sets.** Monsters roam the night: `/sleep` to be safe (and a bigger `/daily` "
                    "tomorrow). No robberies or raids until morning. `/time`")
            elif change == "dawn":
                await self.bot.announcer.send("☀️ **The sun rises!** The monsters burn away. `/time`")
            res = await self.bot.db.run(night.tick, self.candidates())
            for a in res["spawned"]:
                await self.post(a)
            for a in res["ended"]:
                await self.refresh(a)
        except Exception:  # an error must never stop the loop
            log.exception("Night loop failed")

    @night_loop.before_loop
    async def before_night_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(NightCog(bot))
