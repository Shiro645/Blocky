from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import loans, settings
from game.errors import GameError
from utils.ui import ConfirmView, dm, em, report_error

log = logging.getLogger("loans")
NO_PINGS = discord.AllowedMentions.none()


def terms(o: dict) -> str:
    return (f"**{em(o['amount'])}** at **{o['interest']}%** interest: **{em(o['due'])}** to repay "
            f"within **{o['days']} day{'s' if o['days'] > 1 else ''}**")


def offer_embed(o: dict, state: str = "open", loan: dict | None = None) -> discord.Embed:
    lender, borrower = f"<@{o['lender_id']}>", f"<@{o['borrower_id']}>"
    asked = o["proposer_id"] == o["borrower_id"]
    if asked:
        text = f"{borrower} asks {lender} for a loan of {terms(o)}."
    else:
        text = f"{lender} offers {borrower} a loan of {terms(o)}."
    color = discord.Color.blurple()
    if state == "open":
        text += f"\n\n<@{o['answerer_id']}>, do you accept? The offer expires <t:{o['expires_at']}:R>."
    elif state == "accepted" and loan is not None:
        text += (f"\n\n✅ Accepted: {borrower} received {em(o['amount'])}. Repay {em(loan['due'])} "
                 f"before <t:{loan['due_at']}:f> with `/loan repay`.")
        color = discord.Color.green()
    else:
        text += "\n\n✖️ Declined."
        color = discord.Color.dark_grey()
    return discord.Embed(title="💳 Loan request" if asked else "💳 Loan offer", description=text, color=color)


class LoanButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"blocky:loan:(?P<action>accept|decline):(?P<offer_id>\d+)",
):
    """Accept / Decline of a loan offer or request. They survive restarts."""

    def __init__(self, action: str, offer_id: int) -> None:
        accept = action == "accept"
        super().__init__(
            discord.ui.Button(
                label="Accept" if accept else "Decline",
                style=discord.ButtonStyle.success if accept else discord.ButtonStyle.secondary,
                emoji="✅" if accept else None,
                custom_id=f"blocky:loan:{action}:{offer_id}",
            )
        )
        self.action, self.offer_id = action, offer_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(match["action"], int(match["offer_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        try:
            if self.action == "accept":
                res = await db.run(loans.accept, self.offer_id, interaction.user.id)
                embed = offer_embed(res["offer"], "accepted", res["loan"])
            else:
                embed = offer_embed(await db.run(loans.decline, self.offer_id, interaction.user.id), "declined")
            await interaction.response.edit_message(content=None, embed=embed, view=None)
        except Exception as error:
            await report_error(interaction, error)


def offer_view(offer_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(LoanButton("accept", offer_id))
    view.add_item(LoanButton("decline", offer_id))
    return view


def limits_text() -> str:
    c = settings.get()["loans"]
    return (f"Loans: {int(c['min_amount']):,}–{int(c['max_amount']):,} emeralds · interest up to "
            f"{float(c['max_interest']):.0%} · {c['min_days']}–{c['max_days']} days · late: "
            f"+{float(c['late_penalty']):.0%}, then {float(c['garnish']):.0%} of what the borrower receives")


class LoansCog(commands.Cog):
    """/loan: lend and borrow emeralds between players, with interest."""

    loan = app_commands.Group(name="loan", description="Lend and borrow emeralds between players, with interest.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(LoanButton)
        self.loan_loop.start()

    async def cog_unload(self) -> None:
        self.loan_loop.cancel()
        self.bot.remove_dynamic_items(LoanButton)

    async def propose(self, interaction: discord.Interaction, other: discord.Member, lender_id: int, borrower_id: int,
                      amount: int, interest: int, days: int) -> None:
        if other.bot:
            raise GameError("Bots don't lend or borrow.")
        o = await self.bot.db.run(loans.propose, interaction.user.id, lender_id, borrower_id, amount, interest, days)
        await interaction.response.send_message(
            content=other.mention, embed=offer_embed(o), view=offer_view(o["offer_id"]),
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=[other]),
        )

    @loan.command(name="offer", description="Offer a loan to a player: you choose the interest and the duration.")
    @app_commands.describe(member="Who you lend to", amount="Emeralds you lend",
                           interest="Interest in % (0 = free)", days="Days they have to repay")
    async def offer(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1],
                    interest: app_commands.Range[int, 0, 100], days: app_commands.Range[int, 1, 365]):
        await self.propose(interaction, member, interaction.user.id, member.id, amount, interest, days)

    @loan.command(name="ask", description="Ask a player for a loan, with the interest and the duration you propose.")
    @app_commands.describe(member="Who you borrow from", amount="Emeralds you borrow",
                           interest="Interest in % you offer (0 = free)", days="Days you need to repay")
    async def ask(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1],
                  interest: app_commands.Range[int, 0, 100], days: app_commands.Range[int, 1, 365]):
        await self.propose(interaction, member, member.id, interaction.user.id, amount, interest, days)

    @loan.command(name="repay", description="Pay back your loan (everything by default).")
    @app_commands.describe(amount="How much you pay back now (everything left by default)")
    async def repay(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1] | None = None):
        user = interaction.user
        res = await self.bot.db.run(loans.repay, user.id, amount)
        loan = res["loan"]
        lender = f"<@{loan['lender_id']}>"
        if loan["status"] == "repaid":
            text = f"✅ {user.mention} paid back {em(res['paid'])} to {lender}: the loan is fully repaid!"
        else:
            when = "it's late" if loan["status"] == "late" else f"due <t:{loan['due_at']}:R>"
            text = f"💳 {user.mention} paid back {em(res['paid'])} to {lender}: {em(loans.left(loan))} left, {when}."
        await interaction.response.send_message(text, allowed_mentions=NO_PINGS)

    @loan.command(name="list", description="Your debt and the loans you gave.")
    async def list_loans(self, interaction: discord.Interaction):
        data = await self.bot.db.run(loans.overview, interaction.user.id)
        debt = data["debt"]
        garnish = float(settings.get()["loans"]["garnish"])
        if debt is None:
            mine = "Nothing. 🎉"
        elif debt["status"] == "late":
            mine = (f"{em(debt['left'])} to <@{debt['lender_id']}> · ⚠️ **late**: {garnish:.0%} of what you receive "
                    "goes to them, and no /pay, /trade, auction listing or loan until it's paid.")
        else:
            mine = f"{em(debt['left'])} to <@{debt['lender_id']}> · due <t:{debt['due_at']}:R>"
        given = [
            f"<@{g['borrower_id']}> owes {em(g['left'])} · "
            + ("⚠️ **late** (collected automatically)" if g["status"] == "late" else f"due <t:{g['due_at']}:R>")
            for g in data["given"]
        ]
        embed = discord.Embed(title="💳 Your loans", color=discord.Color.blurple())
        embed.add_field(name="You owe", value=mine, inline=False)
        embed.add_field(name="Owed to you", value="\n".join(given) or "Nothing.", inline=False)
        embed.set_footer(text=limits_text())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @loan.command(name="forgive", description="Cancel what a player still owes you.")
    @app_commands.describe(member="The player who owes you")
    async def forgive(self, interaction: discord.Interaction, member: discord.Member):
        user = interaction.user
        debt = await self.bot.db.run(loans.debt_of, member.id)
        if debt is None or debt["lender_id"] != user.id:
            raise GameError(f"{member.mention} doesn't owe you anything.")

        async def do(i: discord.Interaction) -> None:
            res = await self.bot.db.run(loans.forgive, user.id, member.id)
            await i.response.edit_message(content="Done.", view=None)
            await i.followup.send(f"🤝 {user.mention} forgave {member.mention}'s debt ({em(res['forgiven'])}).",
                                  allowed_mentions=NO_PINGS)

        await interaction.response.send_message(
            f"Forgive {member.mention}'s debt of {em(loans.left(debt))}? You won't get it back.",
            view=ConfirmView(user.id, "Forgive", do), ephemeral=True,
        )

    # ---------- background ----------
    @tasks.loop(minutes=1)
    async def loan_loop(self):
        try:
            for event in await self.bot.db.run(loans.tick):
                await self.late(event)
        except Exception:  # an error must never stop the loop
            log.exception("Loan loop failed")

    @loan_loop.before_loop
    async def before_loan_loop(self):
        await self.bot.wait_until_ready()

    def name(self, user_id: int) -> str:
        user = self.bot.get_user(user_id)
        return user.display_name if user else "a player"

    async def late(self, e: dict) -> None:
        """A loan past its deadline: tell both players (a fully paid one also gets the LoanRepaid DM)."""
        loan, left = e["loan"], e["left"]
        guild = getattr(self.bot, "main_guild", None)
        where = f" on **{guild.name}**" if guild else ""
        garnish = float(settings.get()["loans"]["garnish"])
        borrower = self.bot.get_user(loan["borrower_id"])
        if borrower is not None:
            text = f"⏰ Your loan from {self.name(loan['lender_id'])}{where} is late: +{em(e['penalty'])} penalty."
            if e["taken"]:
                text += f" {em(e['taken'])} were taken from your emeralds."
            if left:
                text += (f" **{em(left)}** left: {garnish:.0%} of every emerald you receive goes to them until it's "
                         "paid, and you can't /pay, /trade, list at the auction or take a loan until then. "
                         "Pay it with `/loan repay`.")
            await dm(borrower, text)
        lender = self.bot.get_user(loan["lender_id"])
        if lender is not None and left:
            text = f"⏰ {self.name(loan['borrower_id'])}'s loan{where} is late."
            if e["taken"]:
                text += f" You received {em(e['taken'])}."
            text += f" **{em(left)}** left: you get {garnish:.0%} of everything they receive until it's paid."
            await dm(lender, text)


async def setup(bot: commands.Bot):
    await bot.add_cog(LoansCog(bot))
