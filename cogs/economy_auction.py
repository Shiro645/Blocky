from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import assets, exchange, settings
from utils.autocomplete import owned_asset_choices
from utils.ui import asset_icon, em

log = logging.getLogger("auction")


def listing_line(r: dict) -> str:
    text = f"`#{r['auction_id']}` {asset_icon(r['asset'])} **{assets.describe(r['asset'], r['amount'])}**"
    if r["durability"] is not None:
        text += f" `{r['durability']}/{r['max_durability']}`"
    return text + f" — {em(r['price'])} · <@{r['seller_id']}> · expires <t:{r['expires_at']}:R>"


class AuctionCog(commands.Cog):
    auction = app_commands.Group(name="auction", description="Player auction house: buy and sell between players.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.expire_loop.start()

    async def cog_unload(self) -> None:
        self.expire_loop.cancel()

    async def notify(self, user_id: int, text: str) -> None:
        """Best effort DM (members can have DMs closed)."""
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            await user.send(text)
        except discord.HTTPException:
            pass

    @tasks.loop(minutes=5)
    async def expire_loop(self):
        try:
            await self.expire_tick()
        except Exception:  # an error must never stop the loop
            log.exception("Auction expiry loop failed")

    async def expire_tick(self) -> None:
        expired = await self.bot.db.run(exchange.expire)
        for r in expired:
            await self.notify(
                r["seller_id"],
                f"⌛ Your auction listing **{assets.describe(r['asset'], r['amount'])}** expired and was returned to you.",
            )

    @expire_loop.before_loop
    async def before_expire_loop(self):
        await self.bot.wait_until_ready()

    # ---------- autocomplete ----------
    async def sell_autocomplete(self, interaction: discord.Interaction, current: str):
        return await owned_asset_choices(self.bot, interaction.user.id, current, emeralds=False)

    async def own_listing_autocomplete(self, interaction: discord.Interaction, current: str):
        rows = await self.bot.db.run(exchange.listings_of, interaction.user.id)
        choices = []
        for r in rows:
            name = f"#{r['auction_id']} {assets.describe(r['asset'], r['amount'])} for {r['price']} emeralds"
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name, value=r["auction_id"]))
        return choices[:25]

    # ---------- commands ----------
    @auction.command(name="sell", description="Put something up for sale.")
    @app_commands.describe(item="What to sell", amount="How many", price="Total price in emeralds")
    @app_commands.autocomplete(item=sell_autocomplete)
    async def sell(self, interaction: discord.Interaction, item: str, price: app_commands.Range[int, 1], amount: app_commands.Range[int, 1] = 1):
        r = await self.bot.db.run(exchange.list_for_sale, interaction.user.id, item, amount, price)
        tax = exchange.tax_for(price)
        await interaction.response.send_message(
            f"🏷️ {interaction.user.mention} listed {asset_icon(item)} **{assets.describe(item, amount)}** for **{em(price)}** "
            f"(listing `#{r['auction_id']}`). Buy it with `/auction buy {r['auction_id']}`!",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await interaction.followup.send(
            f"You will receive **{em(price - tax)}** after the {settings.get()['auction']['tax_percent']}% tax. "
            f"Unsold items come back to you <t:{r['expires_at']}:R>.",
            ephemeral=True,
        )

    @auction.command(name="browse", description="Browse the items for sale.")
    @app_commands.describe(search="Filter by name (e.g. diamond, sword)", page="Page number")
    async def browse(self, interaction: discord.Interaction, search: str = "", page: app_commands.Range[int, 1] = 1):
        data = await self.bot.db.run(exchange.browse, search, page)
        embed = discord.Embed(
            title="🏪 Auction house" + (f" — “{search}”" if search else ""),
            description="\n".join(listing_line(r) for r in data["rows"]) or "Nothing for sale right now.",
            color=discord.Color.orange(),
        )
        embed.set_footer(text=f"Page {data['page']}/{data['pages']} · {data['total']} listing(s) · /auction buy <id>")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @auction.command(name="buy", description="Buy a listing from the auction house.")
    @app_commands.describe(listing="Listing number (shown as #id in /auction browse)")
    async def buy(self, interaction: discord.Interaction, listing: app_commands.Range[int, 1]):
        r = await self.bot.db.run(exchange.buy, interaction.user.id, listing)
        what = assets.describe(r["asset"], r["amount"])
        await interaction.response.send_message(
            f"✅ You bought **{what}** for **{em(r['price'])}**. New balance: **{em(r['balance'])}**.",
            ephemeral=True,
        )
        await self.notify(
            r["seller_id"],
            f"💰 Your listing **{what}** was bought by {interaction.user.display_name} "
            f"for {r['price']} emeralds (you received {r['price'] - r['tax']} after tax).",
        )

    @auction.command(name="cancel", description="Take back one of your listings.")
    @app_commands.describe(listing="The listing to take back")
    @app_commands.autocomplete(listing=own_listing_autocomplete)
    async def cancel(self, interaction: discord.Interaction, listing: int):
        r = await self.bot.db.run(exchange.cancel, interaction.user.id, listing)
        await interaction.response.send_message(
            f"✅ Listing `#{listing}` cancelled: {asset_icon(r['asset'])} **{assets.describe(r['asset'], r['amount'])}** returned to you.",
            ephemeral=True,
        )

    @auction.command(name="mine", description="Show your current listings.")
    async def mine(self, interaction: discord.Interaction):
        rows = await self.bot.db.run(exchange.listings_of, interaction.user.id)
        embed = discord.Embed(
            title="🏷️ Your listings",
            description="\n".join(listing_line(r) for r in rows) or "You have nothing for sale.",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AuctionCog(bot))
