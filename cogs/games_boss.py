from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import dimensions, gate, potions, settings
from game.errors import GameError
from utils.checks import check_game_channel
from utils.ui import BaseView, em, join_lines, potion_icon, report_error

log = logging.getLogger("gate")

COLORS = {"lobby": discord.Color.blurple(), "active": discord.Color.dark_red(), "won": discord.Color.gold(),
          "lost": discord.Color.dark_grey(), "cancelled": discord.Color.dark_grey()}


def bar(hp: float, max_hp: float, size: int = 12) -> str:
    full = round(size * max(0.0, hp) / max_hp) if max_hp else 0
    return "█" * full + "░" * (size - full)


def player_line(row: dict, p: gate.Player | None, uid: int) -> str:
    leader = "👑 " if uid == row["leader_id"] else ""
    if p is None:
        return f"{leader}<@{uid}>"
    if not p.alive:
        return f"☠️ {leader}<@{uid}> — fallen · {p.damage:.0f} damage"
    turn = "▶️ " if row["status"] == "active" and row["fight"].current.user_id == uid else ""
    extra = []
    if p.blocks_left:
        extra.append(f"🛡️ {p.blocks_left}")
    if p.withered:
        extra.append("🖤 withered")
    if p.afk >= int(settings.get()["gate_bosses"]["afk_turns"]):
        extra.append("💤 auto")
    max_potions = int(settings.get()["gate_bosses"]["max_potions"])
    return (f"{turn}{leader}<@{uid}> — ❤️ {p.hp:.1f}/{p.max_hp:g} · ⚔️ {p.damage:.0f} · 🧪 {p.potions_used}/{max_potions}"
            + (" · " + " · ".join(extra) if extra else ""))


def fight_embed(row: dict) -> discord.Embed:
    c = settings.get()["gate_bosses"]
    key = row["boss"]
    b = gate.BOSSES[key]
    bc = gate.boss_cfg(key)
    fight: gate.Fight | None = row["fight"]
    lines: list[str] = []
    if row["status"] == "lobby":
        lines.append(f"<@{row['leader_id']}> calls a group to fight the **{b.name}**, who guards the "
                     f"{dimensions.label(b.opens)}. Entry: {em(bc['entry'])} each, up to **{c['max_players']}** "
                     f"players who reached the {dimensions.label(b.home)}. Join with the button; the leader starts "
                     f"when ready (the group closes <t:{row['deadline']}:R>).")
        lines.append(f"It's made for **{c['max_players']}**: come prepared (a shield, potions: "
                     f"{c['max_potions']} each at most). Each survivor of a victory opens the "
                     f"{dimensions.label(b.opens)} and gets the bounty ({em(bc['bounty'])}), a book and {bc['xp']} XP. "
                     "The fallen get nothing.")
    elif row["status"] == "cancelled":
        lines.append("This group was cancelled: entries refunded.")
    elif fight is not None:
        lines.append(f"{b.emoji} **{b.name}** `{bar(fight.hp, fight.max_hp)}` **{fight.hp:.0f}**/{fight.max_hp:.0f} HP"
                     f" · boss turn {fight.rounds}")
        if fight.log:
            lines.append("")
            lines += fight.log[-14:]
        if row["status"] == "active":
            lines.append(f"\n**<@{fight.current.user_id}>'s turn** (before <t:{row['deadline']}:R>, else you attack): "
                         "drink a potion if you want, then **Attack** or **Attack + block**.")
    if row.get("rewards"):
        lines.append("")
        for uid, r in row["rewards"].items():
            text = f"🏆 <@{uid}>: +{em(r['bounty'] + r['looting'])}"
            if r["looting"]:
                text += f" (Looting +{em(r['looting'])})"
            text += f", a **{r['book']}** book, +{r['xp']} XP"
            if r["opened"]:
                text += f" · **the {dimensions.label(r['opened'])} opens!**"
            lines.append(text)
    if row.get("beacon_lit"):
        lines.append("🌟 **The Wither drops a Nether Star: the server's Beacon is lit!** (`/beacon info`)")
    embed = discord.Embed(title=f"{b.emoji} Gate boss — {b.name}", description=join_lines(lines, 4000),
                          color=COLORS.get(row["status"]))
    plist = {p.user_id: p for p in fight.players} if fight else {}
    members = [player_line(row, plist.get(uid), uid) for uid in row["members"]]
    embed.add_field(name=f"Players ({len(row['members'])}/{c['max_players']})", value=join_lines(members), inline=False)
    return embed


class BossButton(discord.ui.DynamicItem[discord.ui.Button],
                 template=r"blocky:gate:(?P<action>join|start|quit|attack|block|potion):(?P<fight_id>\d+)"):
    """The buttons of a gate boss fight. They survive restarts."""

    LOOK = {
        "join": ("Join", "⚔️", discord.ButtonStyle.success),
        "start": ("Start", "▶️", discord.ButtonStyle.primary),
        "quit": ("Leave the group", "🚪", discord.ButtonStyle.secondary),
        "attack": ("Attack", "⚔️", discord.ButtonStyle.danger),
        "block": ("Attack + block", "🛡️", discord.ButtonStyle.primary),
        "potion": ("Drink a potion", "🧪", discord.ButtonStyle.secondary),
    }

    def __init__(self, action: str, fight_id: int, disabled: bool = False) -> None:
        label, emoji, style = self.LOOK[action]
        super().__init__(discord.ui.Button(label=label, emoji=emoji, style=style, disabled=disabled,
                                           custom_id=f"blocky:gate:{action}:{fight_id}"))
        self.action, self.fight_id = action, fight_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(match["action"], int(match["fight_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: GateBossCog | None = interaction.client.get_cog("GateBossCog")  # type: ignore[assignment]
        if cog is None:
            return
        try:
            await cog.click(interaction, self.action, self.fight_id)
        except Exception as error:
            await report_error(interaction, error)


def fight_view(row: dict) -> discord.ui.View | None:
    view = discord.ui.View(timeout=None)
    if row["status"] == "lobby":
        for action in ("join", "start", "quit"):
            view.add_item(BossButton(action, row["fight_id"]))
    elif row["status"] == "active":
        fight: gate.Fight = row["fight"]
        view.add_item(BossButton("attack", row["fight_id"]))
        view.add_item(BossButton("block", row["fight_id"], disabled=fight.current.blocks_left <= 0))
        view.add_item(BossButton("potion", row["fight_id"], disabled=fight.drank or fight.potions_left(fight.current) <= 0))
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
        await self.view.cog.drink(interaction, self.view.fight_id, self.values[0])


class PotionView(BaseView):
    def __init__(self, cog: "GateBossCog", user_id: int, fight_id: int, owned: dict[str, int]):
        super().__init__(allowed_ids={user_id}, timeout=60)
        self.cog, self.fight_id = cog, fight_id
        self.add_item(PotionSelect(owned))


class GateBossCog(commands.Cog):
    """/boss: the gate bosses (Wither, Ender Dragon, Warden) open the next dimensions."""

    group = app_commands.Group(name="boss", description="Gate bosses: beat them in a group to open the next dimension.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(BossButton)
        self.gate_loop.start()

    async def cog_unload(self) -> None:
        self.gate_loop.cancel()
        self.bot.remove_dynamic_items(BossButton)

    # ---------- commands ----------
    @group.command(name="fight", description="Call a group to fight a gate boss: others join before you start.")
    @app_commands.describe(boss="The boss (it lives in a dimension and opens the next one)")
    @app_commands.choices(boss=[app_commands.Choice(name=f"{b.emoji} {b.name}", value=b.key) for b in gate.BOSSES.values()])
    async def fight(self, interaction: discord.Interaction, boss: str):
        check_game_channel(interaction)
        row = await self.bot.db.run(gate.create, interaction.user.id, boss)
        await interaction.response.send_message(embed=fight_embed(row), view=fight_view(row))
        message = await interaction.original_response()
        await self.bot.db.run(gate.set_message, row["fight_id"], message.channel.id, message.id)

    @group.command(name="info", description="The gate bosses: where they live, what they open, when you can fight.")
    async def info(self, interaction: discord.Interaction):
        c = settings.get()["gate_bosses"]

        def load(ctx):
            return dimensions.level(ctx, interaction.user.id), gate.ready_at(ctx, interaction.user.id)

        level, ready = await self.bot.db.run(load)
        lines = [f"🌋 **Nether**: clear the 💀 Nightmare dungeon (`/pve start`): the survivors of wave 5 open it."]
        for b in gate.BOSSES.values():
            bc = gate.boss_cfg(b.key)
            if level > dimensions.level_of(b.home):
                state = "✅ beaten"
            elif level == dimensions.level_of(b.home):
                state = "⚔️ your next gate"
            else:
                state = f"🔒 reach the {dimensions.label(b.home)} first"
            lines.append(f"{b.emoji} **{b.name}** ({dimensions.label(b.home)} → {dimensions.label(b.opens)}) — "
                         f"entry {em(bc['entry'])} · bounty {em(bc['bounty'])} · {state}")
        embed = discord.Embed(
            title="🚪 Gate bosses",
            description=(
                f"Fight them turn by turn in a group of up to **{c['max_players']}** (`/boss fight`): each player in "
                "order drinks a potion if they want, then attacks (with a shield: **Attack + block** stops the boss's "
                f"next strike on you), then the boss plays. Made for {c['max_players']}: come prepared, with "
                f"shields and potions ({c['max_potions']} each at most). The survivors of a victory open the next "
                "dimension and each get the bounty (Looting adds to it), a book (sometimes Mending) and XP; a boss "
                f"you already beat pays {float(c['repeat_reward']):.0%} of it. One fight every "
                f"{float(c['cooldown_hours']):g} h.\n\n" + "\n".join(lines)
            ),
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="🖤 Wither", value="Blasts everyone each turn and withers them: they lose health on its "
                                                 "next turns.", inline=False)
        embed.add_field(name="🐉 Ender Dragon", value="Strikes players at random twice a turn, and breathes fire on "
                                                       "everyone every few turns (no shield stops the breath).",
                        inline=False)
        embed.add_field(name="👁️ Warden", value="Smashes one player very hard; every few turns its **Sonic Boom** "
                                                 "ignores armor and shields.", inline=False)
        embed.add_field(name="You can fight", value=f"<t:{ready}:R>" if ready else "now", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------- buttons ----------
    async def click(self, interaction: discord.Interaction, action: str, fight_id: int) -> None:
        db, uid = self.bot.db, interaction.user.id
        if action == "join":
            row = await db.run(gate.join, fight_id, uid)
        elif action == "quit":
            row = await db.run(gate.leave_lobby, fight_id, uid)
        elif action == "start":
            row = await db.run(gate.start, fight_id, uid)
        elif action in ("attack", "block"):
            row = await db.run(gate.attack, fight_id, uid, action == "block")
        else:  # potion
            row = await db.run(gate.get, fight_id)
            fight = row["fight"]
            if row["status"] != "active" or fight is None:
                raise GameError("This fight isn't running.")
            if fight.current.user_id != uid:
                raise GameError(f"It's <@{fight.current.user_id}>'s turn.")
            owned = await db.run(potions.owned, uid)
            if not owned:
                raise GameError("You have no potions.")
            await interaction.response.send_message("Which potion?", view=PotionView(self, uid, fight_id, owned),
                                                    ephemeral=True)
            return
        await interaction.response.edit_message(embed=fight_embed(row), view=fight_view(row))
        await self.after(row)

    async def drink(self, interaction: discord.Interaction, fight_id: int, key: str) -> None:
        row = await self.bot.db.run(gate.drink, fight_id, interaction.user.id, key)
        await interaction.response.edit_message(content=f"{potion_icon(key)} You drank {potions.label(key)}.", view=None)
        await self.refresh(row)

    async def after(self, row: dict) -> None:
        """Once a message showed the log, start a new one; when a fight ends, the openers get their roles."""
        if row["status"] == "active":
            await self.bot.db.run(gate.clear_log, row["fight_id"])
        if row.get("beacon_lit"):
            cog_b = self.bot.get_cog("BeaconCog")
            if cog_b is not None:
                await cog_b.announce_lit(next(iter(row["rewards"])))  # type: ignore[attr-defined]
        opened = [uid for uid, r in (row.get("rewards") or {}).items() if r["opened"]]
        cog = self.bot.get_cog("DimensionsCog")
        for uid in opened:
            if cog is not None:
                await cog.sync_roles(uid)  # type: ignore[attr-defined]

    async def refresh(self, row: dict) -> None:
        """Update the fight's message (after a potion or a timeout)."""
        channel = self.bot.get_channel(row["channel_id"] or 0)
        if not isinstance(channel, discord.abc.Messageable) or not row["message_id"]:
            return
        try:
            await channel.get_partial_message(row["message_id"]).edit(embed=fight_embed(row), view=fight_view(row))
        except discord.HTTPException:
            log.exception("Could not update a boss fight message")
        await self.after(row)

    # ---------- background ----------
    @tasks.loop(seconds=10)
    async def gate_loop(self):
        try:
            for row in await self.bot.db.run(gate.expire):
                await self.refresh(row)
        except Exception:  # an error must never stop the loop
            log.exception("Gate boss loop failed")

    @gate_loop.before_loop
    async def before_gate_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(GateBossCog(bot))
