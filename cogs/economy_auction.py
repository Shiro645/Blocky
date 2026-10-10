from __future__ import annotations

import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import assets, botstate, exchange, settings
from utils.autocomplete import owned_asset_choices
from utils.config import channel_id
from utils.ui import ConfirmView, asset_icon, em, report_error

log = logging.getLogger("auction")
BOARD_KEY = "market_board"  # "channel_id:message_id" of the board in the market channel
BOARD_PAGE = 10


def listing_line(r: dict) -> str:
    text = f"`#{r['auction_id']}` {asset_icon(r['asset'])} **{assets.describe(r['asset'], r['amount'])}**"
    if r["durability"] is not None:
        text += f" `{r['durability']}/{r['max_durability']}`"
    return text + f" — {em(r['price'])} · <@{r['seller_id']}> · expires <t:{r['expires_at']}:R>"


# ---------------- the market board ----------------
def board_embed(data: dict) -> discord.Embed:
    embed = discord.Embed(
        title="🏪 Auction house",
        description="\n".join(listing_line(r) for r in data["rows"])
        or "Nothing for sale right now. Sell something with `/auction sell`!",
        color=discord.Color.orange(),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=f"Page {data['page']}/{data['pages']} · {data['total']} listing(s) · "
                          "buy with the menu below · updated")
    return embed


def board_view(data: dict) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    if data["rows"]:
        options = [
            discord.SelectOption(
                label=f"#{r['auction_id']} {assets.describe(r['asset'], r['amount'])}"[:100],
                description=f"{r['price']:,} emeralds",
                value=str(r["auction_id"]),
            )
            for r in data["rows"]
        ]
        view.add_item(MarketBuySelect(data["page"], options))
    view.add_item(MarketPageButton(data["page"] - 1, "prev", disabled=data["page"] <= 1))
    view.add_item(MarketPageButton(data["page"] + 1, "next", disabled=data["page"] >= data["pages"]))
    return view


class MarketPageButton(discord.ui.DynamicItem[discord.ui.Button], template=r"blocky:market:(?P<dir>prev|next):(?P<page>\d+)"):
    """◀ ▶ on the board (it shows the same page to everyone). They survive restarts."""

    def __init__(self, page: int, direction: str, disabled: bool = False) -> None:
        super().__init__(discord.ui.Button(
            emoji="◀️" if direction == "prev" else "▶️", style=discord.ButtonStyle.secondary, row=1,
            custom_id=f"blocky:market:{direction}:{max(page, 0)}", disabled=disabled,
        ))
        self.page = max(page, 1)

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["page"]), match["dir"])

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: AuctionCog | None = interaction.client.get_cog("AuctionCog")  # type: ignore[assignment]
        if cog is not None:
            await cog.refresh_board(self.page, interaction)


class MarketBuySelect(discord.ui.DynamicItem[discord.ui.Select], template=r"blocky:market:buy:(?P<page>\d+)"):
    """The board's menu: pick a listing, confirm, it's yours."""

    def __init__(self, page: int, options: list[discord.SelectOption] | None = None) -> None:
        super().__init__(discord.ui.Select(
            placeholder="Buy a listing…", custom_id=f"blocky:market:buy:{page}", row=0,
            options=options or [discord.SelectOption(label="…", value="0")],
        ))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Select, match: re.Match[str], /):
        return cls(int(match["page"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: AuctionCog | None = interaction.client.get_cog("AuctionCog")  # type: ignore[assignment]
        try:
            if cog is None:
                return
            listing_id = int((interaction.data or {}).get("values", ["0"])[0])
            await cog.offer(interaction, listing_id)
        except Exception as error:
            await report_error(interaction, error)


class AuctionCog(commands.Cog):
    auction = app_commands.Group(name="auction", description="Player auction house: buy and sell between players.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.board_lock = asyncio.Lock()
        self._board_shown: dict | None = None  # last board posted, to skip edits that change nothing

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(MarketPageButton, MarketBuySelect)
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
        await self.refresh_board()

    # ---------- the board in the market channel ----------
    async def refresh_board(self, page: int = 1, interaction: discord.Interaction | None = None) -> None:
        """Show the listings on the board of the market channel (posted again if it was deleted).

        With an interaction (◀ ▶), that page is shown; otherwise the board goes back to page 1.
        """
        data = await self.bot.db.run(exchange.browse, "", page, BOARD_PAGE)
        embed, view = board_embed(data), board_view(data)
        if interaction is not None:
            await interaction.response.edit_message(embed=embed, view=view)
            self._board_shown = None
            return
        cid = channel_id("market")
        channel = self.bot.get_channel(cid) if cid else None
        if not isinstance(channel, discord.abc.Messageable):
            return
        async with self.board_lock:
            content = {"rows": data["rows"], "page": data["page"], "pages": data["pages"], "channel": cid}
            if content == self._board_shown:
                return
            saved = await self.bot.db.run(botstate.get, BOARD_KEY)
            if saved and saved.startswith(f"{cid}:"):
                try:
                    message = await channel.fetch_message(int(saved.split(":")[1]))
                    await message.edit(embed=embed, view=view)
                    self._board_shown = content
                    return
                except discord.NotFound:
                    pass  # deleted: post a new one
                except discord.HTTPException:
                    log.warning("Could not update the market board", exc_info=True)
                    return
            try:
                message = await channel.send(embed=embed, view=view)
            except discord.HTTPException:
                log.warning("Could not post the market board in channel %s", cid, exc_info=True)
                return
            await self.bot.db.run(botstate.put, BOARD_KEY, f"{cid}:{message.id}")
            self._board_shown = content

    async def offer(self, interaction: discord.Interaction, listing_id: int) -> None:
        """A listing picked on the board: ask the buyer to confirm (only they see it)."""
        listing = await self.bot.db.run(exchange.get_listing, listing_id)
        what = f"{asset_icon(listing['asset'])} **{assets.describe(listing['asset'], listing['amount'])}**"

        async def do(confirm: discord.Interaction) -> None:
            await self.complete_purchase(confirm, listing_id, edit=True)

        await interaction.response.send_message(
            f"Buy {what} from <@{listing['seller_id']}> for **{em(listing['price'])}**?",
            view=ConfirmView(interaction.user.id, "Buy", do), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def complete_purchase(self, interaction: discord.Interaction, listing_id: int, edit: bool = False) -> None:
        r = await self.bot.db.run(exchange.buy, interaction.user.id, listing_id)
        what = assets.describe(r["asset"], r["amount"])
        text = f"✅ You bought **{what}** for **{em(r['price'])}**. New balance: **{em(r['balance'])}**."
        if edit:
            await interaction.response.edit_message(content=text, view=None)
        else:
            await interaction.response.send_message(text, ephemeral=True)
        await self.notify(
            r["seller_id"],
            f"💰 Your listing **{what}** was bought by {interaction.user.display_name} "
            f"for {r['price']} emeralds (you received {r['price'] - r['tax']} after tax).",
        )
        await self.refresh_board()

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
        await self.refresh_board()

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
        await self.complete_purchase(interaction, listing)

    @auction.command(name="cancel", description="Take back one of your listings.")
    @app_commands.describe(listing="The listing to take back")
    @app_commands.autocomplete(listing=own_listing_autocomplete)
    async def cancel(self, interaction: discord.Interaction, listing: int):
        r = await self.bot.db.run(exchange.cancel, interaction.user.id, listing)
        await interaction.response.send_message(
            f"✅ Listing `#{listing}` cancelled: {asset_icon(r['asset'])} **{assets.describe(r['asset'], r['amount'])}** returned to you.",
            ephemeral=True,
        )
        await self.refresh_board()

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
