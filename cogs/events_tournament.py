from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import settings, tournament
from game.tournament import round_name
from utils.checks import staff_only
from utils.config import role_id
from utils.ui import em, join_lines, report_error

log = logging.getLogger("tournament")

ARENA = "🏟️"


def prize_text(settings: dict) -> str:
    first, second, third = (list(settings["prize_split"]) + [0, 0, 0])[:3]
    return f"🥇 {first}% · 🥈 {second}% · 🥉 {third}% shared by the semi-finalists"


def match_line(m: dict) -> str:
    if m["player2"] is None:
        return f"<@{m['player1']}> — bye"
    if m["winner"] is None:
        return f"<@{m['player1']}> vs <@{m['player2']}>"
    loser = m["player2"] if m["winner"] == m["player1"] else m["player1"]
    return f"⚔️ **<@{m['winner']}>** beats <@{loser}> ({m['winner_hp']:g} HP left)"


def next_pairs(matches: list[dict]) -> list[str]:
    """The matches of the next round, from the winners of this one."""
    winners = [m["winner"] for m in sorted(matches, key=lambda m: m["slot"])]
    return [f"<@{winners[i]}> vs <@{winners[i + 1]}>" for i in range(0, len(winners) - 1, 2)]


def registration_embed(t: dict, players: int, closed: bool = False) -> discord.Embed:
    s = settings.get()["tournament"]
    if closed:
        state = "the tournament was cancelled" if t["status"] == "cancelled" else "see the bracket with `/tournament bracket`"
        return discord.Embed(
            title=f"{ARENA} Weekend tournament: registrations are closed",
            description=f"**{players}** player(s) registered · pot **{em(t['pot'])}**: {state}.",
            color=discord.Color.dark_grey(),
        )
    closes = (
        f"before <t:{t['closes_at']}:F> (<t:{t['closes_at']}:R>)" if t["closes_at"]
        else "until staff starts the tournament"
    )
    first = f"<t:{t['starts_at']}:F>" if t["starts_at"] else "right after the draw"
    embed = discord.Embed(
        title=f"{ARENA} Weekend tournament: registrations are open!",
        description=(
            f"Click **Join** (or `/tournament join`) {closes}.\n"
            f"Entry: **{em(int(s['entry_fee']))}** · the server adds **{em(int(s['house_bonus']))}** to the pot. "
            "Changed your mind? **Leave** refunds you until the draw.\n\n"
            f"The bracket is drawn when registrations close. First round: {first}, then one round "
            f"every {int(s['round_minutes'])} minutes. Fights are automatic, with the gear you have "
            f"equipped (it doesn't wear out).\n\n**Prizes**: {prize_text(s)}, plus the tournament champion role."
        ),
        color=discord.Color.orange(),
    )
    embed.add_field(name="Registered", value=f"**{players}** player(s) · pot **{em(t['pot'])}**", inline=False)
    return embed


class RegistrationButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"blocky:tournament:(?P<action>join|leave):(?P<tid>\d+)"
):
    """Join / Leave buttons of the registration message. They survive restarts."""

    def __init__(self, action: str, tournament_id: int) -> None:
        join = action == "join"
        super().__init__(
            discord.ui.Button(
                label="Join" if join else "Leave",
                style=discord.ButtonStyle.success if join else discord.ButtonStyle.secondary,
                emoji="⚔️" if join else None,
                custom_id=f"blocky:tournament:{action}:{tournament_id}",
            )
        )
        self.action, self.tournament_id = action, tournament_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(match["action"], int(match["tid"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: TournamentCog | None = interaction.client.get_cog("TournamentCog")  # type: ignore[assignment]
        if cog is None:
            return
        try:
            await cog.register_click(interaction, self.action, self.tournament_id)
        except Exception as error:
            await report_error(interaction, error)


def registration_view(tournament_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(RegistrationButton("join", tournament_id))
    view.add_item(RegistrationButton("leave", tournament_id))
    return view


class TournamentCog(commands.Cog):
    tournament_group = app_commands.Group(name="tournament", description="Weekend tournament: register and follow the bracket.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(RegistrationButton)
        self.tick_loop.start()

    async def cog_unload(self) -> None:
        self.tick_loop.cancel()
        self.bot.remove_dynamic_items(RegistrationButton)

    # ---------- clock ----------
    @tasks.loop(minutes=1)
    async def tick_loop(self):
        try:
            for event in await self.bot.db.run(tournament.tick):
                await self.announce(event)
        except Exception:  # an error must never stop the loop
            log.exception("Tournament loop failed")

    @tick_loop.before_loop
    async def before_tick_loop(self):
        await self.bot.wait_until_ready()

    # ---------- announcements ----------
    async def post(
        self, embed: discord.Embed, ping: bool = False, view: discord.ui.View | None = None
    ) -> discord.Message | None:
        channel = self.bot.announcer.channel("events") or self.bot.announcer.channel()
        if channel is None:
            return None
        rid = role_id("event_ping") if ping else 0
        try:
            return await channel.send(
                content=f"<@&{rid}>" if rid else None,
                embed=embed,
                view=view,
                # Only the configured role is pinged, never @everyone / @here.
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, users=False, roles=[discord.Object(rid)] if rid else False
                ),
            )
        except discord.HTTPException:
            log.exception("Could not post the tournament announcement")
            return None

    async def refresh_registration(self, tournament_id: int, closed: bool = False) -> None:
        """Update the registration message: number of players, or closed (no more buttons)."""
        data = await self.bot.db.run(tournament.registration, tournament_id)
        t = data["tournament"]
        if not t["channel_id"] or not t["message_id"]:
            return
        channel = self.bot.get_channel(t["channel_id"])
        if not isinstance(channel, discord.abc.Messageable):
            return
        view = None if closed else registration_view(tournament_id)
        try:
            await channel.get_partial_message(t["message_id"]).edit(
                embed=registration_embed(t, data["players"], closed), view=view
            )
        except discord.HTTPException:
            log.exception("Could not update the tournament registration message")

    async def register_click(self, interaction: discord.Interaction, action: str, tournament_id: int) -> None:
        if action == "join":
            res = await self.bot.db.run(tournament.join, interaction.user.id, tournament_id)
            text = f"✅ You are registered for the tournament ({em(res['fee'])} paid). Good luck!"
        else:
            res = await self.bot.db.run(tournament.leave, interaction.user.id, tournament_id)
            text = f"You left the tournament: {em(res['refund'])} refunded."
        data = await self.bot.db.run(tournament.registration, tournament_id)
        await interaction.response.edit_message(
            embed=registration_embed(data["tournament"], data["players"]), view=registration_view(tournament_id)
        )
        await interaction.followup.send(text, ephemeral=True)

    async def announce(self, event: dict) -> None:
        if event["type"] == "opened":
            await self.announce_opened(event["tournament"])
        elif event["type"] == "cancelled":
            await self.refresh_registration(event["tournament"]["tournament_id"], closed=True)
            embed = discord.Embed(
                title=f"{ARENA} Tournament cancelled",
                description=(
                    f"Only **{event['players']}** player(s) registered (minimum {event['minimum']}). "
                    "Every entry fee has been refunded. See you next weekend!"
                ),
                color=discord.Color.dark_grey(),
            )
            await self.post(embed)
            await self.move_champion_role(None)
        elif event["type"] == "drawn":
            await self.refresh_registration(event["tournament"]["tournament_id"], closed=True)
            await self.announce_drawn(event)
        elif event["type"] == "round":
            await self.announce_round(event)

    async def announce_opened(self, t: dict) -> None:
        msg = await self.post(registration_embed(t, 0), ping=True, view=registration_view(t["tournament_id"]))
        if msg is not None:
            await self.bot.db.run(tournament.set_message, t["tournament_id"], msg.channel.id, msg.id)

    async def announce_drawn(self, event: dict) -> None:
        t = event["tournament"]
        embed = discord.Embed(
            title=f"{ARENA} The bracket is drawn!",
            description=(
                f"**{event['players']}** players · pot **{em(t['pot'])}**\n"
                f"First round <t:{t['next_round_at']}:F> (<t:{t['next_round_at']}:R>). "
                "Equip your best gear before then!"
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(
            name=round_name(1, t["rounds"]),
            value=join_lines([match_line(m) for m in event["matches"]]),
            inline=False,
        )
        await self.post(embed)

    async def announce_round(self, event: dict) -> None:
        t = event["tournament"]
        played = [match_line(m) for m in event["matches"] if m["player2"] is not None]
        embed = discord.Embed(
            title=f"{ARENA} {round_name(event['round'], event['rounds'])} — results",
            description=join_lines(played, limit=4000),
            color=discord.Color.orange(),
        )
        if "final" not in event:
            nxt = round_name(event["round"] + 1, event["rounds"])
            at = event["next_round_at"]
            embed.add_field(
                name=f"Next: {nxt}",
                value=f"<t:{at}:t> (<t:{at}:R>)\n" + join_lines(next_pairs(event["matches"]), limit=950),
                inline=False,
            )
            await self.post(embed)
            return
        await self.post(embed)
        await self.announce_winner(event["final"], t)

    async def announce_winner(self, final: dict, t: dict) -> None:
        medals = {final["winner"]: "🥇", final["runner_up"]: "🥈"}
        lines = [f"{medals.get(uid, '🥉')} <@{uid}> +{em(amount)}" for uid, amount in final["payout"]]
        embed = discord.Embed(
            title="🏆 Tournament champion!",
            description=(
                f"<@{final['winner']}> wins the weekend tournament and the **{em(final['pot'])}** pot!\n\n"
                + "\n".join(lines)
            ),
            color=discord.Color.gold(),
        )
        await self.post(embed)
        await self.move_champion_role(final["winner"])

    async def move_champion_role(self, champion_id: int | None) -> None:
        """The tournament champion role belongs to the last winner, until the next tournament ends."""
        rid = role_id("tournament_champion")
        guild = self.bot.main_guild
        if not rid or guild is None:
            return
        role = guild.get_role(rid)
        if role is None:
            log.warning("roles.tournament_champion %s not found", rid)
            return
        try:
            for member in list(role.members):
                if member.id != champion_id:
                    await member.remove_roles(role, reason="Blocky tournament ended")
            if champion_id:
                member = guild.get_member(champion_id)
                if member is not None and role not in member.roles:
                    await member.add_roles(role, reason="Blocky tournament champion")
        except discord.HTTPException:
            log.exception("Could not move the tournament champion role (check Manage Roles and role order)")

    # ---------- commands ----------
    @tournament_group.command(name="join", description="Register for the weekend tournament (entry fee).")
    async def join(self, interaction: discord.Interaction):
        res = await self.bot.db.run(tournament.join, interaction.user.id)
        await interaction.response.send_message(
            f"{ARENA} {interaction.user.mention} entered the weekend tournament for {em(res['fee'])}! "
            f"({res['players']} players · pot {em(res['tournament']['pot'])})",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await self.refresh_registration(res["tournament"]["tournament_id"])

    @tournament_group.command(name="leave", description="Cancel your registration (refunded until the draw).")
    async def leave(self, interaction: discord.Interaction):
        res = await self.bot.db.run(tournament.leave, interaction.user.id)
        await interaction.response.send_message(
            f"You left the tournament: {em(res['refund'])} refunded.", ephemeral=True
        )
        await self.refresh_registration(res["tournament"]["tournament_id"])

    @tournament_group.command(name="info", description="Weekend tournament: dates, pot, your status.")
    async def info(self, interaction: discord.Interaction):
        data = await self.bot.db.run(tournament.overview, interaction.user.id)
        s, t = data["settings"], data["tournament"]
        embed = discord.Embed(title=f"{ARENA} Weekend tournament", color=discord.Color.orange())
        if t is None or t["status"] in ("finished", "cancelled"):
            text = f"Next registrations: <t:{data['next_opening']}:F> (<t:{data['next_opening']}:R>)."
            if t is not None and t["status"] == "finished":
                text += f"\nLast champion: <@{t['winner_id']}>."
                if data["me"] and data["me"]["prize"]:
                    text += f" You won {em(data['me']['prize'])}."
            embed.description = text
        elif t["status"] == "open":
            closes = f"<t:{t['closes_at']}:F> (<t:{t['closes_at']}:R>)" if t["closes_at"] else "when staff starts it"
            embed.description = (
                f"**Registrations are open** until {closes}.\n"
                f"**{data['players']}** player(s) · pot **{em(t['pot'])}**\n"
                + ("✅ You are registered." if data["me"] else "Register with `/tournament join`.")
            )
        else:
            nxt = round_name(t["round"] + 1, t["rounds"])
            if data["me"] is None:
                me = "You are not in this tournament."
            elif data["me"]["eliminated_round"]:
                me = f"You were eliminated in the {round_name(data['me']['eliminated_round'], t['rounds']).lower()}."
            else:
                me = "⚔️ You are still in!"
            embed.description = (
                f"**{nxt}** <t:{t['next_round_at']}:R> · {len(data['alive'])} player(s) left · "
                f"pot **{em(t['pot'])}**\n{me}\nSee the matches with `/tournament bracket`."
            )
        embed.add_field(
            name="Rules",
            value=(
                f"Entry {em(int(s['entry_fee']))} (refunded if you leave before the draw) · server bonus "
                f"{em(int(s['house_bonus']))}\n{int(s['min_players'])}–{int(s['max_players'])} players, "
                f"single elimination, one round every {int(s['round_minutes'])} min.\n"
                "Automatic fights with your equipped gear, no wear.\n"
                f"{prize_text(s)}."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tournament_group.command(name="bracket", description="Show the tournament bracket and results.")
    async def bracket(self, interaction: discord.Interaction):
        data = await self.bot.db.run(tournament.bracket)
        t = data["tournament"]
        embed = discord.Embed(title=f"{ARENA} Tournament bracket", color=discord.Color.orange())
        by_round: dict[int, list[dict]] = {}
        for m in data["matches"]:
            by_round.setdefault(m["round"], []).append(m)
        for rnd, rows in by_round.items():
            embed.add_field(name=round_name(rnd, t["rounds"]), value=join_lines([match_line(m) for m in rows]), inline=False)
        if t["status"] == "running":
            embed.set_footer(text=f"Next: {round_name(t['round'] + 1, t['rounds'])}")
            embed.description = f"Next round <t:{t['next_round_at']}:R> · pot {em(t['pot'])}"
        elif t["status"] == "finished":
            embed.description = f"🏆 Champion: <@{t['winner_id']}> · pot {em(t['pot'])}"
        else:
            embed.description = "This tournament was cancelled."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------- staff ----------
    @app_commands.command(name="tournament_admin", description="STAFF: Open, advance or cancel the tournament now.")
    @app_commands.describe(action="What to do")
    @app_commands.choices(action=[
        app_commands.Choice(name="Open registrations now", value="open"),
        app_commands.Choice(name="Next step now (draw, then next round)", value="next"),
        app_commands.Choice(name="Cancel and refund", value="cancel"),
    ])
    @staff_only()
    async def tournament_admin(self, interaction: discord.Interaction, action: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if action == "open":
            t = await self.bot.db.run(tournament.staff_open)
            await self.announce_opened(t)
            text = "Registrations opened."
        elif action == "next":
            event = await self.bot.db.run(tournament.staff_round)
            await self.announce(event)
            text = "Bracket drawn." if event["type"] == "drawn" else (
                "Tournament cancelled (not enough players)." if event["type"] == "cancelled"
                else f"{round_name(event['round'], event['rounds'])} played."
            )
        else:
            res = await self.bot.db.run(tournament.staff_cancel)
            await self.refresh_registration(res["tournament"]["tournament_id"], closed=True)
            embed = discord.Embed(
                title=f"{ARENA} Tournament cancelled",
                description="The staff cancelled the tournament. Every entry fee has been refunded.",
                color=discord.Color.dark_grey(),
            )
            await self.post(embed)
            text = f"Tournament cancelled, {len(res['refunded'])} player(s) refunded."
        await interaction.followup.send(f"✅ {text}", ephemeral=True)
        log_embed = discord.Embed(
            title=f"{ARENA} Tournament: {action}",
            description=f"{text}\nBy {interaction.user.mention} (`{interaction.user}`)",
            color=discord.Color.orange(),
        )
        await self.bot.announcer.send(embed=log_embed, channel="staff_log")


async def setup(bot: commands.Bot):
    await bot.add_cog(TournamentCog(bot))
