from __future__ import annotations

import asyncio
import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from game import duel, potions, settings
from game.errors import GameError
from utils.checks import staff_only
from utils.ui import BaseView, em, join_lines, potion_icon, progress_bar, report_error

log = logging.getLogger("duel")

POTION_CHOICES = [app_commands.Choice(name=p.name, value=p.key) for p in potions.POTIONS.values()]


class DuelView(BaseView):
    """The challenge: the opponent accepts or declines."""

    def __init__(self, cog: "DuelCog", challenger: discord.Member, opponent: discord.Member, stake: int):
        timeout = settings.get()["duel"]["request_timeout_seconds"]
        super().__init__(allowed_ids={challenger.id, opponent.id}, timeout=timeout)
        self.cog = cog
        self.challenger, self.opponent, self.stake = challenger, opponent, stake
        self.done = False

    async def on_timeout(self) -> None:
        self.cog.pending.discard(self.challenger.id)
        await super().on_timeout()

    @discord.ui.button(label="Fight!", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            return await interaction.response.send_message("❌ Only the challenged player can accept.", ephemeral=True)
        if self.done:
            return await interaction.response.defer()
        self.done = True
        try:
            await self.cog.start_fight(interaction, self)
        except GameError:
            self.done = False
            raise
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.done:
            return await interaction.response.defer()
        self.done = True
        self.cog.pending.discard(self.challenger.id)
        self.disable_all()
        self.stop()
        verb = "declined" if interaction.user.id == self.opponent.id else "cancelled"
        embed = discord.Embed(
            title="⚔️ Duel " + verb,
            description=f"{interaction.user.mention} {verb} the duel.",
            color=discord.Color.dark_grey(),
        )
        await interaction.response.edit_message(content=None, embed=embed, view=self)


class AttackButton(discord.ui.Button):
    def __init__(self, fight_view: "FightView"):
        super().__init__(label="Attack", style=discord.ButtonStyle.danger, emoji="⚔️", row=0)
        self.fight_view = fight_view

    async def callback(self, interaction: discord.Interaction):
        await self.fight_view.play(interaction, None)


class PotionSelect(discord.ui.Select):
    def __init__(self, fight_view: "FightView", options: list[discord.SelectOption]):
        super().__init__(placeholder="🧪 Drink a potion, then attack…", options=options, row=1)
        self.fight_view = fight_view

    async def callback(self, interaction: discord.Interaction):
        await self.fight_view.play(interaction, self.values[0])


class FightView(discord.ui.View):
    """A duel being fought: the player whose turn it is attacks, with or without a potion."""

    def __init__(self, cog: "DuelCog", challenger: discord.Member, opponent: discord.Member, stake: int, setup: dict):
        super().__init__(timeout=None)
        self.cog = cog
        self.members = {challenger.id: challenger, opponent.id: opponent}
        self.stake = stake
        self.duel_id: int = setup["duel_id"]
        self.fight: duel.Fight = setup["fight"]
        self.owned: dict[int, dict[str, int]] = setup["potions"]
        self.lock = asyncio.Lock()
        self.turn_no = 0
        self.missed = {uid: 0 for uid in self.members}
        self.afk: int | None = None
        self.deadline = 0
        self.timer: asyncio.Task | None = None
        self.message: discord.Message | None = None
        self.build()

    # ---------- components ----------
    def build(self) -> None:
        self.clear_items()
        self.add_item(AttackButton(self))
        current = self.fight.current
        if self.fight.potions_left(current) <= 0:
            return
        options = [
            discord.SelectOption(
                label=f"{potions.label(key)} ×{amount}", value=key,
                description=potions.effect_text(key)[:100], emoji=potion_icon(key) or None,
            )
            for key, amount in sorted(self.owned[current.user_id].items()) if amount > 0
        ]
        if options:
            self.add_item(PotionSelect(self, options[:25]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.members:
            await interaction.response.send_message("❌ This isn't your duel.", ephemeral=True)
            return False
        if self.fight.over or interaction.user.id != self.fight.current.user_id:
            await interaction.response.send_message("⏳ It's not your turn.", ephemeral=True)
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        await report_error(interaction, error)

    # ---------- turns ----------
    def start_timer(self) -> None:
        self.deadline = int(time.time() + int(settings.get()["duel"]["turn_seconds"]))
        if self.timer is not None and self.timer is not asyncio.current_task():
            self.timer.cancel()
        self.timer = asyncio.create_task(self._timer(self.turn_no))

    async def _timer(self, turn_no: int) -> None:
        await asyncio.sleep(int(settings.get()["duel"]["turn_seconds"]))
        try:
            await self.play(None, None, turn_no)
        except Exception:
            log.exception("Automatic duel turn failed")

    async def play(self, interaction: discord.Interaction | None, potion: str | None, turn_no: int | None = None) -> None:
        """Play the current player's turn (interaction None = they ran out of time on turn `turn_no`)."""
        async with self.lock:
            # A click may have played the turn while the timer was waiting for the lock.
            if self.fight.over or (turn_no is not None and turn_no != self.turn_no):
                if interaction is not None:
                    await interaction.response.defer()
                return
            uid = self.fight.current.user_id
            if potion:
                self.fight.check_potion(potion)
                await self.cog.bot.db.run(potions.drink, uid, potion)
                self.owned[uid][potion] -= 1
            self.missed[uid] = self.missed[uid] + 1 if interaction is None else 0
            self.fight.play(self.cog.rng, potion)
            if not self.fight.over and self.missed[uid] >= int(settings.get()["duel"]["afk_turns"]):
                self.afk = uid
                self.fight.auto_play(self.cog.rng)
            self.turn_no += 1
            if self.fight.over:
                await self.end(interaction)
                return
            self.build()
            self.start_timer()
            embed = self.cog.fight_embed(self)
            if interaction is not None:
                await interaction.response.edit_message(content=None, embed=embed, view=self)
            elif self.message is not None:
                await self.message.edit(content=None, embed=embed, view=self)

    async def end(self, interaction: discord.Interaction | None) -> None:
        if self.timer is not None and self.timer is not asyncio.current_task():
            self.timer.cancel()
        self.stop()
        self.cog.finish(*self.members)
        res = await self.cog.bot.db.run(duel.finish, self.duel_id, self.fight)
        embed = self.cog.result_embed(self, res)
        if interaction is not None:
            await interaction.response.edit_message(content=None, embed=embed, view=None)
        elif self.message is not None:
            await self.message.edit(content=None, embed=embed, view=None)


class DuelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rng = random.Random()
        self.cooldown_until: dict[int, float] = {}
        self.pending: set[int] = set()  # challengers with an open request
        self.busy: set[int] = set()  # players in a fight

    async def cog_load(self) -> None:
        refunded = await self.bot.db.run(duel.refund_interrupted)
        if refunded:
            log.info("Refunded %d duel(s) interrupted by a restart", len(refunded))

    def finish(self, *user_ids: int) -> None:
        cooldown = settings.get()["duel"]["cooldown_seconds"]
        for uid in user_ids:
            self.pending.discard(uid)
            self.busy.discard(uid)
            self.cooldown_until[uid] = time.monotonic() + cooldown

    def check_cooldown(self, member: discord.abc.User) -> None:
        if member.id in self.busy:
            raise GameError(f"{member.mention} is already in a duel.")
        left = self.cooldown_until.get(member.id, 0) - time.monotonic()
        if left > 0:
            raise GameError(f"{member.mention} is still recovering from a duel. Try again in **{left:.0f}s**.")

    async def start_fight(self, interaction: discord.Interaction, request: DuelView) -> None:
        self.check_cooldown(request.challenger)
        self.check_cooldown(request.opponent)
        setup = await self.bot.db.run(duel.start, request.challenger.id, request.opponent.id, request.stake)
        self.pending.discard(request.challenger.id)
        self.busy.update({request.challenger.id, request.opponent.id})
        view = FightView(self, request.challenger, request.opponent, request.stake, setup)
        view.message = interaction.message
        view.start_timer()
        await interaction.response.edit_message(content=None, embed=self.fight_embed(view), view=view)

    @app_commands.command(name="duel", description="Challenge a player: both bet the stake, the winner takes it all.")
    @app_commands.describe(member="Who you want to fight", stake="Emeralds each player bets")
    async def duel_cmd(self, interaction: discord.Interaction, member: discord.Member, stake: app_commands.Range[int, 1]):
        if member.bot or member.id == interaction.user.id:
            raise GameError("Pick another player.")
        if interaction.user.id in self.pending:
            raise GameError("You already have a duel request waiting.")
        self.check_cooldown(interaction.user)
        self.check_cooldown(member)

        def check(ctx):
            duel.check_stake(ctx, interaction.user.id, stake)
            duel.check_stake(ctx, member.id, stake)

        await self.bot.db.run(check)

        view = DuelView(self, interaction.user, member, stake)
        self.pending.add(interaction.user.id)
        embed = discord.Embed(
            title="⚔️ Duel challenge!",
            description=(
                f"{interaction.user.mention} challenges {member.mention}!\n"
                f"Stake: **{em(stake)}** each — the winner takes **{em(stake * 2)}**.\n"
                f"Turn by turn: attack, or drink a potion first (up to {potions.max_per_duel()} per duel).\n\n"
                f"{member.mention}, do you accept? (expires in {int(view.timeout)}s)"
            ),
            color=discord.Color.red(),
        )
        await interaction.response.send_message(
            content=member.mention, embed=embed, view=view,
            allowed_mentions=discord.AllowedMentions(users=[member]),
        )
        view.message = await interaction.original_response()

    # ---------- potions ----------
    @app_commands.command(name="potions", description="Your potions and what they do in duels.")
    async def potions_cmd(self, interaction: discord.Interaction):
        owned = await self.bot.db.run(potions.owned, interaction.user.id)
        keys = list(potions.POTIONS) + sorted(k for k in owned if k not in potions.POTIONS)
        lines = [
            f"{potion_icon(key)} **{potions.label(key)}** × {owned.get(key, 0)} — {potions.effect_text(key)}"
            for key in keys
        ]
        embed = discord.Embed(
            title="🧪 Potions",
            description=(
                "\n".join(lines)
                + f"\n\nIn a duel, on your turn: drink one potion, then attack (up to {potions.max_per_duel()} per duel). "
                "Potions come from drops and bosses; reinforced potions (II) only from the villager."
            ),
            color=discord.Color.purple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="add_potion", description="STAFF: Give potions to a member.")
    @app_commands.choices(potion=POTION_CHOICES)
    @staff_only()
    async def add_potion(
        self, interaction: discord.Interaction, member: discord.Member, potion: str,
        amount: app_commands.Range[int, 1, 100] = 1, level: app_commands.Range[int, 1, potions.MAX_LEVEL] = 1,
    ):
        potion = potions.key_of(potion, level)
        await self.bot.db.run(potions.give, member.id, potion, amount)
        await interaction.response.send_message(
            f"✅ Gave {amount} × {potion_icon(potion)} **{potions.label(potion)}** to {member.mention}.", ephemeral=True
        )

    # ---------- embeds ----------
    def turn_line(self, view: FightView, t: duel.Turn) -> str:
        attacker = view.members[t.attacker].display_name
        defender = view.members[t.defender].display_name
        bits = []
        if t.potion:
            text = f"{potion_icon(t.potion)} {potions.name(t.potion)}"
            if t.healed:
                text += f" (+{t.healed:g} HP)"
            if t.direct:
                text += f" ({t.direct:g} damage)"
            bits.append(text)
        for i, hit in enumerate(t.hits):
            bits.append(("⚡ again " if i else "") + ("💥 CRIT " if hit.crit else "") + f"**{hit.damage:.1f}**")
        return f"**{attacker}** → {defender}: " + " · ".join(bits) + f" — {defender} {t.defender_hp:g} HP"

    def fighter_field(self, view: FightView, fighter: duel.Fighter) -> tuple[str, str]:
        marker = "▶️ " if not view.fight.over and fighter is view.fight.current else ""
        speed = f" · ⚡ {fighter.speed_turns} turn(s)" if fighter.speed_turns else ""
        value = (
            f"`{progress_bar(int(fighter.hp), int(fighter.max_hp), 12)}` {fighter.hp:.1f}/{fighter.max_hp:g} HP\n"
            f"⚔️ {fighter.attack:g} · 🛡️ {fighter.reduction:.0%} · 🧪 {view.fight.potions_left(fighter)} left{speed}"
        )
        return marker + view.members[fighter.user_id].display_name, value

    def fight_embed(self, view: FightView) -> discord.Embed:
        a, b = (view.members[f.user_id] for f in view.fight.fighters)
        lines = [self.turn_line(view, t) for t in view.fight.log[-6:]] or ["The fight begins!"]
        embed = discord.Embed(
            title=f"⚔️ {a.display_name} vs {b.display_name}",
            description=join_lines(lines, limit=3500),
            color=discord.Color.red(),
        )
        for fighter in view.fight.fighters:
            name, value = self.fighter_field(view, fighter)
            embed.add_field(name=name, value=value, inline=True)
        current = view.members[view.fight.current.user_id]
        embed.add_field(
            name=f"Turn {view.fight.rounds + 1} · pot {view.stake * 2:,} emeralds",
            value=f"{current.mention}: attack, or drink a potion first. Auto attack <t:{view.deadline}:R>.",
            inline=False,
        )
        return embed

    def result_embed(self, view: FightView, res: dict) -> discord.Embed:
        winner = view.members[res["winner"]]
        lines = [self.turn_line(view, t) for t in view.fight.log[-6:]]
        embed = discord.Embed(
            title=f"🏆 {winner.display_name} wins the duel!",
            description=join_lines(lines, limit=3500),
            color=discord.Color.gold(),
        )
        for fighter in view.fight.fighters:
            name, value = self.fighter_field(view, fighter)
            embed.add_field(name=name, value=value, inline=True)
        embed.add_field(
            name="Pot", value=f"<@{res['winner']}> takes **{em(res['stake'] * 2)}** after {res['rounds']} turns", inline=False
        )
        if view.afk:
            embed.add_field(
                name="⏱️ Auto", value=f"<@{view.afk}> missed their turns: the end was played automatically.", inline=False
            )
        if res["broken"]:
            embed.add_field(
                name="🔨 Broken",
                value="\n".join(f"<@{uid}>'s {name}" for uid, name in res["broken"]),
                inline=False,
            )
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(DuelCog(bot))
