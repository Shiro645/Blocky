from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import potions, pve, settings
from game.errors import GameError
from utils.checks import check_game_channel
from utils.ui import BaseView, em, join_lines, potion_icon, report_error

log = logging.getLogger("pve")

COLORS = {"lobby": discord.Color.blurple(), "between": discord.Color.orange(),
          "done": discord.Color.dark_grey(), "cancelled": discord.Color.dark_grey()}
STATUS = {"dead": "☠️", "left": "🚪", "cleared": "🏆"}


def member_line(run: dict, m: dict) -> str:
    leader = "👑 " if m["user_id"] == run["leader_id"] and m["status"] == "in" else ""
    who = f"{leader}<@{m['user_id']}>"
    hero = m["hero"]
    if m["status"] == "dead":
        return f"☠️ {who} — dead" + (f", lost {em(m['loot'])}" if m["loot"] else "")
    if m["status"] in ("left", "cleared"):
        return f"{STATUS[m['status']]} {who} — {'cleared it' if m['status'] == 'cleared' else 'left'}: +{em(m['paid'])}"
    if hero is None:
        return who
    max_potions = int(settings.get()["pve"]["max_potions"])
    waiting = ""
    if run["status"] == "between":
        waiting = "✅ " if pve.is_ready(run, m) else "⏳ "
    return (f"{waiting}{who} — ❤️ {hero.hp:.1f}/{hero.max_hp:g} · 💰 {em(m['loot'])} · 🧪 {m['potions']}/{max_potions}"
            + (" · 💪 potion on" if hero.strength or hero.speed or hero.harming else ""))


def run_embed(run: dict, last: dict | None = None) -> discord.Embed:
    c = settings.get()["pve"]
    diff = run["difficulty"]
    title = f"⚔️ Dungeon — {pve.label(diff)}"
    lines: list[str] = []
    if run["status"] == "lobby":
        entry = int(c["difficulties"][diff]["entry"])
        lines.append(f"<@{run['leader_id']}> opens a dungeon run. Entry: {em(entry)} each, up to "
                     f"**{c['max_players']}** players. Join with the button; the leader starts when ready "
                     f"(the group closes <t:{run['deadline']}:R>).")
        lines.append("Health isn't restored between waves. Each wave cleared adds to your loot, "
                     "but **if you die you lose it**: leave in time!")
    elif run["status"] == "cancelled":
        lines.append("This group was cancelled: entries refunded.")
    else:
        if last is not None:
            title += f" · wave {last['wave']}/{len(pve.WAVES)} " + ("cleared ✅" if last["result"]["cleared"] else "lost ☠️")
            lines += last["result"]["log"][-12:]
            if last["result"]["cleared"] and not last["cleared_all"]:
                lines.append(f"💰 +{em(last['reward'])} loot and +{last['xp']} XP each")
            if last["cleared_all"]:
                lines.append(f"🏆 **The dungeon is cleared!** Loot +{float(c['clear_bonus']):.0%}, paid to everyone left.")
        if run["status"] == "between":
            nxt = run["wave"] + 1
            lines.append(f"\n**Next: wave {nxt}/{len(pve.WAVES)}** — {pve.wave_text(nxt, len(run['in']))} "
                         f"(+{em(pve.wave_reward(diff, nxt))} each)")
        elif run["status"] == "done" and last is None:
            lines.append("This run is over.")
    embed = discord.Embed(title=title, description=join_lines(lines, 4000), color=COLORS.get(run["status"]))
    members = [member_line(run, m) for m in run["members"]]
    embed.add_field(name=f"Players ({len(run['members'])}/{c['max_players']})", value=join_lines(members), inline=False)
    if run["status"] == "lobby":
        waves = [f"{w}. {pve.wave_text(w)} — {em(pve.wave_reward(diff, w))}" for w in range(1, 6)]
        waves.append(f"Clear all {len(pve.WAVES)}: loot +{float(c['clear_bonus']):.0%}")
        embed.add_field(name="Waves (per player)", value="\n".join(waves), inline=False)
    elif run["status"] == "between":
        embed.set_footer(text="Everyone clicks Ready (✅) or leaves with their loot: the next wave starts when all "
                              "are ready. No answer in time = you leave with your loot. Anyone can drink a potion.")
        embed.add_field(name="Decide before", value=f"<t:{run['deadline']}:R>", inline=True)
    return embed


class PveButton(discord.ui.DynamicItem[discord.ui.Button],
                template=r"blocky:pve:(?P<action>join|start|quit|ready|next|potion|leave):(?P<run_id>\d+):(?P<wave>\d+)"):
    """The buttons of a dungeon run. They survive restarts."""

    LOOK = {
        "join": ("Join", "⚔️", discord.ButtonStyle.success),
        "start": ("Start", "▶️", discord.ButtonStyle.primary),
        "quit": ("Leave the group", "🚪", discord.ButtonStyle.secondary),
        "ready": ("Ready", "✅", discord.ButtonStyle.danger),
        "next": ("Ready", "✅", discord.ButtonStyle.danger),  # messages posted before the Ready button
        "potion": ("Drink a potion", "🧪", discord.ButtonStyle.secondary),
        "leave": ("Leave with my loot", "🚪", discord.ButtonStyle.success),
    }

    def __init__(self, action: str, run_id: int, wave: int = 0) -> None:
        label, emoji, style = self.LOOK[action]
        if action in ("ready", "next"):
            label = f"Ready for wave {wave + 1}"
        super().__init__(discord.ui.Button(label=label, emoji=emoji, style=style,
                                           custom_id=f"blocky:pve:{action}:{run_id}:{wave}"))
        self.action, self.run_id, self.wave = action, run_id, wave

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(match["action"], int(match["run_id"]), int(match["wave"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: PveCog | None = interaction.client.get_cog("PveCog")  # type: ignore[assignment]
        if cog is None:
            return
        try:
            await cog.click(interaction, self.action, self.run_id, self.wave)
        except Exception as error:
            await report_error(interaction, error)


def run_view(run: dict) -> discord.ui.View | None:
    view = discord.ui.View(timeout=None)
    if run["status"] == "lobby":
        for action in ("join", "start", "quit"):
            view.add_item(PveButton(action, run["run_id"]))
    elif run["status"] == "between":
        for action in ("ready", "potion", "leave"):
            view.add_item(PveButton(action, run["run_id"], run["wave"]))
    else:
        return None
    return view


class PotionSelect(discord.ui.Select):
    view: "PotionView"

    def __init__(self, owned: dict[str, int]):
        options = [discord.SelectOption(label=f"{potions.label(k)} ×{n}", value=k, emoji=potion_icon(k),
                                        description=potions.effect_text(k)[:100])
                   for k, n in sorted(owned.items())][:25]
        super().__init__(placeholder="Choose a potion…", options=options)

    async def callback(self, interaction: discord.Interaction):
        await self.view.cog.drink(interaction, self.view.run_id, self.values[0])


class PotionView(BaseView):
    def __init__(self, cog: "PveCog", user_id: int, run_id: int, owned: dict[str, int]):
        super().__init__(allowed_ids={user_id}, timeout=60)
        self.cog, self.run_id = cog, run_id
        self.add_item(PotionSelect(owned))


class PveCog(commands.Cog):
    """/pve: a dungeon of 5 waves, alone or in a group."""

    group = app_commands.Group(name="pve", description="Dungeon: 5 waves of monsters, alone or in a group.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(PveButton)
        self.pve_loop.start()

    async def cog_unload(self) -> None:
        self.pve_loop.cancel()
        self.bot.remove_dynamic_items(PveButton)

    # ---------- commands ----------
    @group.command(name="start", description="Open a dungeon run: others can join before you start.")
    @app_commands.describe(difficulty="Harder = more expensive, stronger monsters, bigger loot")
    @app_commands.choices(difficulty=[app_commands.Choice(name=f"{emoji} {name}", value=key)
                                      for key, (name, emoji) in pve.DIFFICULTIES.items()])
    async def start(self, interaction: discord.Interaction, difficulty: str):
        check_game_channel(interaction)
        run = await self.bot.db.run(pve.create, interaction.user.id, difficulty)
        await interaction.response.send_message(embed=run_embed(run), view=run_view(run))
        message = await interaction.original_response()
        await self.bot.db.run(pve.set_message, run["run_id"], message.channel.id, message.id)

    @group.command(name="info", description="Difficulties, waves, rewards and when you can play again.")
    async def info(self, interaction: discord.Interaction):
        c = settings.get()["pve"]
        ready = await self.bot.db.run(pve.ready_at, interaction.user.id)
        lines = []
        for key in pve.DIFFICULTIES:
            d = c["difficulties"][key]
            total = sum(pve.wave_reward(key, w) for w in range(1, 6))
            lines.append(f"{pve.label(key)} — entry {em(d['entry'])} · monsters ×{float(d['strength']):g} · "
                         f"loot up to {em(round(total * (1 + float(c['clear_bonus']))))}")
        waves = [f"{w}. {pve.wave_text(w)}" for w in range(1, 6)]
        embed = discord.Embed(
            title="⚔️ Dungeon",
            description=(
                f"{len(pve.WAVES)} waves, alone or in a group (`/pve start`). Health isn't restored between waves. Each wave "
                "cleared adds to your loot, but if you die you lose it (and the entry): leave in time! "
                f"Clearing all {len(pve.WAVES)} gives +{float(c['clear_bonus']):.0%}.\n\n" + "\n".join(lines)
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Waves (per player)", value="\n".join(waves), inline=False)
        when = f"<t:{ready}:R>" if ready > discord.utils.utcnow().timestamp() else "now"
        embed.add_field(name="You can play", value=when, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------- buttons ----------
    async def click(self, interaction: discord.Interaction, action: str, run_id: int, wave: int) -> None:
        db, uid = self.bot.db, interaction.user.id
        last = None
        if action == "join":
            run = await db.run(pve.join, run_id, uid)
        elif action == "quit":
            run = await db.run(pve.leave_lobby, run_id, uid)
        elif action == "start":
            last = await db.run(pve.start, run_id, uid)
            run = last["run"]
        elif action in ("ready", "next"):  # "next": a button posted before the update
            res = await db.run(pve.ready, run_id, uid, wave)
            run, last = res["run"], res["last"]
            shown = interaction.message.embeds if interaction.message else []
            if last is None and shown:
                # Still waiting for others: keep the story of the last wave, only the players change.
                embed = run_embed(run)
                embed.title, embed.description = shown[0].title, shown[0].description
                await interaction.response.edit_message(embed=embed, view=run_view(run))
                return
        elif action == "leave":
            res = await db.run(pve.leave, run_id, uid)
            await interaction.response.send_message(f"🚪 You left the dungeon with {em(res['paid'])}.", ephemeral=True)
            await self.refresh(res["run"], res["last"])  # the others may have been waiting for you
            return
        else:  # potion
            run = await db.run(pve.get, run_id)
            if run["status"] != "between" or uid not in [m["user_id"] for m in run["in"]]:
                raise GameError("You are not fighting in this run.")
            owned = await db.run(potions.owned, uid)
            if not owned:
                raise GameError("You have no potions.")
            await interaction.response.send_message("Which potion?", view=PotionView(self, uid, run_id, owned),
                                                    ephemeral=True)
            return
        await interaction.response.edit_message(embed=run_embed(run, last), view=run_view(run))

    async def drink(self, interaction: discord.Interaction, run_id: int, key: str) -> None:
        res = await self.bot.db.run(pve.drink, run_id, interaction.user.id, key)
        await interaction.response.edit_message(content=f"{potion_icon(key)} {potions.label(key)}: {res['effect']}.",
                                                view=None)
        await self.refresh(res["run"])

    async def refresh(self, run: dict, last: dict | None = None) -> None:
        """Update the run's message (after a potion, a departure or a timeout; `last`: a wave just played)."""
        channel = self.bot.get_channel(run["channel_id"] or 0)
        if not isinstance(channel, discord.abc.Messageable) or not run["message_id"]:
            return
        try:
            await channel.get_partial_message(run["message_id"]).edit(embed=run_embed(run, last), view=run_view(run))
        except discord.HTTPException:
            log.exception("Could not update the dungeon message")

    # ---------- background ----------
    @tasks.loop(minutes=1)
    async def pve_loop(self):
        try:
            for event in await self.bot.db.run(pve.expire):
                await self.refresh(event["run"], event.get("last"))
        except Exception:  # an error must never stop the loop
            log.exception("PVE loop failed")

    @pve_loop.before_loop
    async def before_pve_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(PveCog(bot))
