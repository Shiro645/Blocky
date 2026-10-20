from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.games_boss import PotionSelect, bar
from game import potions, settings, teams, war
from game.errors import GameError
from game.raid_fight import Fighter, RaidFight
from utils.checks import check_game_channel, staff_only
from utils.ui import BaseView, em, join_lines, potion_icon, report_error

log = logging.getLogger("war")

REASONS = {"duel": "⚔️ duel won", "rob": "🦹 robbery", "rob_stopped": "🚨 robbery stopped",
           "raid": "🏴 raid won", "raid_defended": "🛡️ raid pushed back"}
COLORS = {"gathering": discord.Color.orange(), "defending": discord.Color.red(), "fighting": discord.Color.dark_red(),
          "won": discord.Color.dark_red(), "lost": discord.Color.green(), "cancelled": discord.Color.dark_grey()}


def tag(team: dict | None) -> str:
    return f"[{team['tag']}] {team['name']}" if team else "a disbanded team"


def raid_embed(raid: dict) -> discord.Embed:
    w = settings.get()["war"]
    a, d = tag(raid["attacker"]), tag(raid["defender"])
    lines = []
    if raid["status"] == "gathering":
        lines.append(f"<@{raid['leader_id']}> gathers **{a}** to raid **{d}**'s chest! Members of {a}: join with the "
                     f"button ({w['raid_min_attackers']} to {w['raid_max_attackers']}). The party leaves "
                     f"<t:{raid['deadline']}:R>, or when the leader launches it.")
    elif raid["status"] == "defending":
        lines.append(f"🏴 **{a}** is at the gates of **{d}**'s chest! Members of {d}: click **Defend** "
                     f"(up to {w['raid_max_defenders']}). The assault comes <t:{raid['deadline']}:R>; nobody there, "
                     "the chest is plundered.")
    elif raid["status"] == "cancelled":
        lines.append("This raid was called off.")
    elif raid["status"] == "fighting":
        fight = war.fight_of(raid)
        lines.append(f"⚔️ **The assault on {d}'s chest!** Round {fight.rounds + 1}/{w['raid_max_rounds']}"
                     + (f" · 🧱 walls -{fight.walls:.0%}" if fight.walls else "")
                     + (f" · 🏹 {fight.arrows} arrow(s) a round" if fight.arrows else ""))
        if fight.log:
            lines.append("")
            lines += fight.log[-12:]
        lines.append(f"\n**{fight.current.mention}'s turn** (before <t:{raid['deadline']}:R>, else they attack): "
                     "drink a potion if you want, then **Attack** (a random enemy) or **Attack + block**.")
    else:
        lines += list(raid["log"])
        if raid["status"] == "won":
            lines.append(f"\n🏴 **{a} plundered {d}'s chest: {em(raid['stolen'])} taken!**")
        else:
            lines.append(f"\n🛡️ **{d} pushed the raid back!**")
        lines += [f"🎯 <@{b['hunter_id']}> claims the bounty on <@{b['target_id']}>'s head: {em(b['amount'])}!"
                  for b in raid.get("bounties", [])]
        if raid.get("worn"):
            lines.append("🔨 Worn out by the raid: " + ", ".join(war.DEFENSES[k] for k in raid["worn"])
                         + " lost a level.")
    embed = discord.Embed(title=f"🏴 Raid on {d}", description=join_lines(lines, 4000),
                          color=COLORS.get(raid["status"]))
    fight = war.fight_of(raid) if raid["status"] == "fighting" else None
    if fight is not None:
        for side, name in (("attack", "Attackers"), ("defend", "Defenders")):
            embed.add_field(name=name, value=join_lines([fighter_line(fight, f) for f in fight.side(side)]),
                            inline=False)
    else:
        embed.add_field(name=f"Attackers ({len(raid['attackers'])})",
                        value=join_lines([f"<@{u}>" for u in raid["attackers"]], empty="—"), inline=True)
        embed.add_field(name=f"Defenders ({len(raid['defenders'])})",
                        value=join_lines([f"<@{u}>" for u in raid["defenders"]], empty="—"), inline=True)
    return embed


def fighter_line(fight: RaidFight, f: Fighter) -> str:
    if not f.alive:
        return f"☠️ {f.mention} — fallen"
    turn = "▶️ " if fight.current is f else ""
    extra = [f"🛡️ {f.blocks_left}"] if f.blocks_left else []
    if not f.golem and f.afk >= int(settings.get()["gate_bosses"]["afk_turns"]):
        extra.append("💤 auto")
    return (f"{turn}{f.mention} `{bar(f.hp, f.max_hp, 8)}` ❤️ {f.hp:.1f}/{f.max_hp:g} · ⚔️ {f.damage:.0f}"
            + (" · " + " · ".join(extra) if extra else ""))


class RaidButton(discord.ui.DynamicItem[discord.ui.Button],
                 template=r"blocky:raid:(?P<action>join|launch|leave|defend|attack|block|potion):(?P<raid_id>\d+)"):
    """The buttons of a raid. They survive restarts."""

    LOOK = {"join": ("Join the raid", "🏴", discord.ButtonStyle.danger),
            "launch": ("Launch", "▶️", discord.ButtonStyle.primary),
            "leave": ("Leave", "🚪", discord.ButtonStyle.secondary),
            "defend": ("Defend", "🛡️", discord.ButtonStyle.success),
            "attack": ("Attack", "⚔️", discord.ButtonStyle.danger),
            "block": ("Attack + block", "🛡️", discord.ButtonStyle.primary),
            "potion": ("Potion", "🧪", discord.ButtonStyle.secondary)}

    def __init__(self, action: str, raid_id: int, disabled: bool = False) -> None:
        label, emoji, style = self.LOOK[action]
        super().__init__(discord.ui.Button(label=label, emoji=emoji, style=style, disabled=disabled,
                                           custom_id=f"blocky:raid:{action}:{raid_id}"))
        self.action, self.raid_id = action, raid_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(match["action"], int(match["raid_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: WarCog | None = interaction.client.get_cog("WarCog")  # type: ignore[assignment]
        if cog is None:
            return
        try:
            await cog.click(interaction, self.action, self.raid_id)
        except Exception as error:
            await report_error(interaction, error)


def raid_view(raid: dict) -> discord.ui.View | None:
    view = discord.ui.View(timeout=None)
    if raid["status"] == "gathering":
        for action in ("join", "launch", "leave"):
            view.add_item(RaidButton(action, raid["raid_id"]))
    elif raid["status"] == "defending":
        view.add_item(RaidButton("defend", raid["raid_id"]))
    elif raid["status"] == "fighting":
        fight = war.fight_of(raid)
        view.add_item(RaidButton("attack", raid["raid_id"]))
        view.add_item(RaidButton("block", raid["raid_id"], disabled=fight.current.blocks_left <= 0))
        view.add_item(RaidButton("potion", raid["raid_id"],
                                 disabled=fight.drank or fight.potions_left(fight.current) <= 0))
    else:
        return None
    return view


class RaidPotionView(BaseView):
    """PotionSelect (cogs/games_boss.py) calls cog.drink(interaction, fight_id, key): here fight_id is the raid's."""

    def __init__(self, cog: "WarCog", user_id: int, raid_id: int, owned: dict[str, int]):
        super().__init__(allowed_ids={user_id}, timeout=60)
        self.cog, self.fight_id = cog, raid_id
        self.add_item(PotionSelect(owned))


class WarCog(commands.Cog):
    """/war and the raids: the weekly gang war between teams."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(RaidButton)
        self.war_loop.start()

    async def cog_unload(self) -> None:
        self.war_loop.cancel()
        self.bot.remove_dynamic_items(RaidButton)

    @app_commands.command(name="war", description="This week's gang war: the teams' points, the pot and the latest feats.")
    async def war_cmd(self, interaction: discord.Interaction):
        data = await self.bot.db.run(war.overview)
        w = settings.get()["war"]
        rows = [f"**#{i}** [{t['tag']}] {t['name']} — **{t['points']}** pts" for i, t in enumerate(data["standings"], 1)]
        prizes = " / ".join(f"{float(p):.0%}" for p in w["prizes"])
        embed = discord.Embed(
            title="🏴 Gang war of the week",
            description=(f"Every team of at least {w['min_members']} members is at war with all the others. "
                         f"**Pot: {em(data['pot'])}** — the top {len(w['prizes'])} share it ({prizes}, after a "
                         f"{float(w['tax']):.0%} tax) when the week ends, into their chests."),
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="Standings", value=join_lines(rows[:15], empty="No team at war yet."), inline=False)
        feats = [f"[{f['tag'] or '?'}] {REASONS.get(f['reason'], f['reason'])}"
                 + (f" by <@{f['user_id']}>" if f["user_id"] else "") + f" (+{f['points']})" for f in data["feats"]]
        embed.add_field(name="Latest feats", value=join_lines(feats, empty="Nothing yet this week."), inline=False)
        p = w["points"]
        embed.set_footer(text=f"Points: duel won vs an enemy +{p['duel']} (max {w['duel_pair_cap']} a day per pair) · "
                              f"robbery on an enemy +{p['rob']} · stopping one +{p['rob_stopped']} · raid won "
                              f"+{p['raid']} · raid pushed back +{p['raid_defended']}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="war_chest", description="STAFF: Set a team's chest.")
    @app_commands.describe(team="Tag or name of the team", amount="Emeralds in its chest")
    @staff_only()
    async def war_chest(self, interaction: discord.Interaction, team: str, amount: app_commands.Range[int, 0]):
        def run(ctx):
            found = teams.find_team(ctx, team)
            war.set_chest(ctx, found["team_id"], amount)
            return found

        found = await self.bot.db.run(run)
        await interaction.response.send_message(f"✅ [{found['tag']}]'s chest now holds {em(amount)}.", ephemeral=True)
        await self.bot.announcer.send(f"🔧 {interaction.user.mention} set [{found['tag']}]'s chest to {em(amount)}.",
                                      channel="staff_log")

    # ---------- raids ----------
    async def start_raid(self, interaction: discord.Interaction, target: str) -> None:
        check_game_channel(interaction)
        raid = await self.bot.db.run(war.start_raid, interaction.user.id, target)
        await interaction.response.send_message(embed=raid_embed(raid), view=raid_view(raid))
        message = await interaction.original_response()
        await self.bot.db.run(war.set_raid_message, raid["raid_id"], message.channel.id, message.id)

    async def click(self, interaction: discord.Interaction, action: str, raid_id: int) -> None:
        db, uid = self.bot.db, interaction.user.id
        if action in ("join", "defend"):
            raid = await db.run(war.join_raid, raid_id, uid)
        elif action == "leave":
            raid = await db.run(war.leave_raid, raid_id, uid)
        elif action == "launch":
            raid = await db.run(war.launch_raid, raid_id, uid)
        elif action in ("attack", "block"):
            await db.run(war.raid_present, raid_id, uid)
            raid = await db.run(war.raid_attack, raid_id, uid, action == "block")
        else:  # potion
            await db.run(war.raid_present, raid_id, uid)
            raid = await db.run(war.get_raid, raid_id)
            fight = war.fight_of(raid) if raid["status"] == "fighting" else None
            if fight is None:
                raise GameError("This fight is over.")
            if fight.current.user_id != uid or fight.current.golem:
                raise GameError(f"It's {fight.current.mention}'s turn.")
            owned = await db.run(potions.owned, uid)
            if not owned:
                raise GameError("You have no potions.")
            await interaction.response.send_message("Which potion?", view=RaidPotionView(self, uid, raid_id, owned),
                                                    ephemeral=True)
            return
        await interaction.response.edit_message(embed=raid_embed(raid), view=raid_view(raid))
        await self.after(raid)
        if raid.get("launched"):
            await self.call_defenders(raid)

    async def drink(self, interaction: discord.Interaction, raid_id: int, key: str) -> None:
        raid = await self.bot.db.run(war.raid_drink, raid_id, interaction.user.id, key)
        await interaction.response.edit_message(content=f"{potion_icon(key)} You drank {potions.label(key)}.", view=None)
        await self.refresh(raid)

    async def after(self, raid: dict) -> None:
        """Once a message showed the fight's log, start a new one."""
        if raid["status"] == "fighting":
            await self.bot.db.run(war.clear_fight_log, raid["raid_id"])

    async def call_defenders(self, raid: dict) -> None:
        """The party left: ping the defending team's members where the raid is."""
        channel = self.bot.get_channel(raid["channel_id"] or 0)
        if not isinstance(channel, discord.abc.Messageable):
            return
        ids = await self.bot.db.run(lambda ctx: [m["user_id"] for m in teams.members(ctx, raid["defender_team"])])
        try:
            await channel.send(
                " ".join(f"<@{u}>" for u in ids) + f" 🏴 **{tag(raid['attacker'])}** is raiding your chest! "
                f"Defend it before <t:{raid['deadline']}:t> (button on the raid's message).",
                allowed_mentions=discord.AllowedMentions(users=[discord.Object(u) for u in ids]),
            )
        except discord.HTTPException:
            log.warning("Could not call the defenders of raid %s", raid["raid_id"])

    async def call_fighters(self, raid: dict) -> None:
        """The assault starts: ping everyone in it, it's played turn by turn."""
        channel = self.bot.get_channel(raid["channel_id"] or 0)
        if not isinstance(channel, discord.abc.Messageable):
            return
        ids = raid["attackers"] + raid["defenders"]
        try:
            await channel.send(" ".join(f"<@{u}>" for u in ids) + " ⚔️ The assault begins: it's played turn by turn "
                               "on the raid's message. Don't miss your turn!",
                               allowed_mentions=discord.AllowedMentions(users=[discord.Object(u) for u in ids]))
        except discord.HTTPException:
            log.warning("Could not call the fighters of raid %s", raid["raid_id"])

    async def refresh(self, raid: dict) -> None:
        channel = self.bot.get_channel(raid["channel_id"] or 0)
        if not isinstance(channel, discord.abc.Messageable) or not raid["message_id"]:
            return
        try:
            await channel.get_partial_message(raid["message_id"]).edit(embed=raid_embed(raid), view=raid_view(raid))
        except discord.HTTPException:
            log.warning("Could not update a raid message", exc_info=True)
        await self.after(raid)

    # ---------- background ----------
    @tasks.loop(seconds=10)  # the raids' turns last 30 s
    async def war_loop(self):
        try:
            res = await self.bot.db.run(war.weekly)
            if res and res["podium"]:
                lines = [f"**#{t['place']}** [{t['tag']}] {t['name']} — {t['points']} pts → {em(t['paid'])} in "
                         "their chest" for t in res["podium"]]
                await self.bot.announcer.send("🏴 **The gang war of the week is over!**\n" + "\n".join(lines)
                                              + f"\nA new war starts: this week's pot is {em(res['pot'])}. `/war`")
            for raid in await self.bot.db.run(war.due_raids):
                await self.refresh(raid)
                if raid.get("launched"):
                    await self.call_defenders(raid)
                if raid.get("started"):
                    await self.call_fighters(raid)
        except Exception:  # an error must never stop the loop
            log.exception("War loop failed")

    @war_loop.before_loop
    async def before_war_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(WarCog(bot))
