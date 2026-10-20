from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import bounty, settings
from game.errors import GameError
from utils.ui import em, join_lines

log = logging.getLogger("bounty")


class BountyCog(commands.Cog):
    """/bounty: emeralds on a player's head, for whoever beats them."""

    group = app_commands.Group(name="bounty", description="Put a bounty on a player's head, or hunt one down.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bounty_loop.start()

    async def cog_unload(self) -> None:
        self.bounty_loop.cancel()

    @group.command(name="place", description="Put a bounty on a player's head (anonymous): whoever beats them takes it.")
    @app_commands.describe(member="Who you want hunted", amount="One of the bounty tiers")
    async def place(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if member.bot:
            raise GameError("Bots have no head to put a bounty on.")
        res = await self.bot.db.run(bounty.place, interaction.user.id, member.id, amount)
        more = f" There is now **{em(res['total'])}** on their head." if res["total"] > amount else ""
        await interaction.response.send_message(
            f"🎯 Your bounty of **{em(amount)}** is on {member.mention}'s head until <t:{res['expires_at']}:f>.{more} "
            "Nobody knows it's you. Unclaimed, it comes back to you minus "
            f"{float(settings.get()['bounty']['refund_tax']):.0%}.", ephemeral=True)

    @place.autocomplete("amount")
    async def amount_choices(self, interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=f"{t:,} emeralds", value=t) for t in bounty.tiers() if current in str(t)][:25]

    @group.command(name="list", description="The bounties on players' heads, the biggest first.")
    async def list_cmd(self, interaction: discord.Interaction):
        rows = await self.bot.db.run(bounty.board)
        lines = [f"**#{i}** <@{r['target_id']}> — **{em(r['total'])}**"
                 + (f" ({r['n']} bounties)" if r["n"] > 1 else "") + f" · next one ends <t:{r['next_expiry']}:R>"
                 for i, r in enumerate(rows, 1)]
        embed = discord.Embed(title="🎯 Wanted", description=join_lines(lines[:20], 4000, empty="No bounty right now."),
                              color=discord.Color.dark_red())
        embed.set_footer(text="Beat them in a duel, rob them or make them fall in a raid to claim it. /bounty info")
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="info", description="How bounties work, and yours: the ones you put and the one on your head.")
    async def info(self, interaction: discord.Interaction):
        c = settings.get()["bounty"]
        mine = await self.bot.db.run(bounty.mine, interaction.user.id)
        tiers = " / ".join(em(t) for t in bounty.tiers())
        embed = discord.Embed(
            title="🎯 Bounties",
            description=(
                f"Put one of the tiers ({tiers}) on a player's head with `/bounty place`: you and they need level "
                f"**{c['min_level']}**, never on yourself or a teammate. Bounties on the same player add up and the "
                "payer stays anonymous.\n"
                "**Claim it** by beating the target in a duel, a successful `/rob` on them, or the blow that makes "
                "them fall in a raid (never their teammates): the hunter takes everything on their head.\n"
                f"A bounty lasts **{c['days']} days**; unclaimed, its payer gets it back minus "
                f"**{float(c['refund_tax']):.0%}**. After a claim, no new bounty on that player for "
                f"**{c['protection_hours']} h**."
            ),
            color=discord.Color.dark_red(),
        )
        placed = [f"<@{b['target_id']}> — {em(b['amount'])} · ends <t:{b['expires_at']}:R>" for b in mine["placed"]]
        embed.add_field(name="Your bounties", value=join_lines(placed, empty="None."), inline=False)
        head = f"**{em(mine['on_head'])}**" if mine["on_head"] else "Nothing."
        if mine["protected_until"]:
            head += f" Safe from new bounties until <t:{mine['protected_until']}:f>."
        embed.add_field(name="On your head", value=head, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tasks.loop(minutes=10)
    async def bounty_loop(self):
        try:
            await self.bot.db.run(bounty.expire)  # the payers are told by private message (utils/announcer.py)
        except Exception:  # an error must never stop the loop
            log.exception("Bounty loop failed")

    @bounty_loop.before_loop
    async def before_bounty_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(BountyCog(bot))
