from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from game import dimensions, enchants, leaderboard, mining, players, settings, shop
from game.catalog import BLOCK_TYPES, DIMENSION_BLOCKS, DIMENSIONS, GEAR_ITEMS, MATERIALS, block_name
from game.db import Ctx
from game.errors import GameError
from utils.config import channel_ids
from utils.ui import EMOJI, BaseView, ConfirmView, block_icon, em, gear_label, item_label, join_lines, scrap_icon


def _inventory(ctx: Ctx, user_id: int, viewer_id: int) -> dict:
    if user_id != viewer_id and ctx.one("SELECT 1 FROM users WHERE user_id=?;", (user_id,)) is None:
        raise GameError(f"<@{user_id}> hasn't played yet.")
    return {
        "blocks": players.get_blocks(ctx, user_id),
        "items": players.get_items(ctx, user_id),
        "gear": shop.get_gear(ctx, user_id),
        "emeralds": players.get_emeralds(ctx, user_id),
        "unlocked": dimensions.unlocked(ctx, user_id),
        "dimension": dimensions.current(ctx, user_id),
        "fortune": leaderboard.fortunes(ctx).get(user_id, 0),
    }


INVENTORY_PAGES = {
    "overview": ("📋", "Overview"),
    "blocks": ("🧱", "Blocks"),
    "resources": ("⛏️", "Resources"),
    "gear": ("⚔️", "Gear"),
    "books": ("📚", "Books & potions"),
}
RESOURCES = ("ingot", "scrap", "lapis", "stick")


def _gear_order(g: dict) -> tuple:
    return (not g["equipped"], GEAR_ITEMS.index(g["item"]) if g["item"] in GEAR_ITEMS else 99,
            -MATERIALS.index(g["material"]) if g["material"] in MATERIALS else 0, g["gear_id"])


def _items_of(inv: dict, kinds: tuple[str, ...]) -> list[str]:
    def order(entry):
        (item, material), _ = entry
        tier = MATERIALS.index(material) if material in MATERIALS else 0
        return kinds.index(item), tier, material
    mine = [entry for entry in inv["items"].items() if entry[0][0] in kinds]
    return [item_label(item, material, amount) for (item, material), amount in sorted(mine, key=order)]


def inventory_embed(inv: dict, member: discord.abc.User, page: str) -> discord.Embed:
    """One page of a player's inventory."""
    emoji, name = INVENTORY_PAGES[page]
    embed = discord.Embed(title=f"{member.display_name}'s Inventory · {emoji} {name}", color=discord.Color.dark_green())
    blocks_value = sum(amount * players.block_value(b) for b, amount in inv["blocks"].items())
    if page == "overview":
        count = lambda kinds: sum(a for (item, _), a in inv["items"].items() if item in kinds)
        equipped = [g for g in inv["gear"] if g["equipped"]]
        embed.description = (
            f"{EMOJI['emerald']} **{inv['emeralds']:,}** emeralds\n".lstrip()
            + f"💰 Total fortune: {em(inv['fortune'])} (blocks {em(blocks_value)})\n"
            + f"📍 In the {dimensions.label(inv['dimension'])}\n\n"
            + f"🧱 {sum(inv['blocks'].values()):,} blocks · ⛏️ {count(RESOURCES):,} resources · "
            + f"⚔️ {len(inv['gear'])} pieces of gear · 📚 {count(('book',))} books · 🧪 {count(('potion',))} potions"
        )
        embed.add_field(name="Equipped", inline=False, value=join_lines(
            [gear_label(g) for g in sorted(equipped, key=_gear_order)], empty="Nothing equipped."))
    elif page == "blocks":
        for dimension in DIMENSIONS:
            if dimension not in inv["unlocked"] and not any(inv["blocks"].get(b) for b in DIMENSION_BLOCKS[dimension]):
                continue  # a dimension they haven't reached
            lines = [f"{block_icon(b)} **{block_name(b)}**: {inv['blocks'].get(b, 0):,} ({em(players.block_value(b))} each)"
                     for b in DIMENSION_BLOCKS[dimension]]
            embed.add_field(name=dimensions.label(dimension), value=join_lines(lines), inline=False)
        embed.set_footer(text=f"Sell value: {blocks_value:,} emeralds")
    elif page == "resources":
        embed.description = join_lines(_items_of(inv, RESOURCES), limit=4096, empty="No resources yet.")
    elif page == "gear":
        pieces = sorted(inv["gear"], key=_gear_order)
        embed.add_field(name="🟢 Equipped", inline=False, value=join_lines(
            [gear_label(g) for g in pieces if g["equipped"]], empty="Nothing equipped."))
        embed.add_field(name="▫️ In the chest", inline=False, value=join_lines(
            [gear_label(g) for g in pieces if not g["equipped"]], empty="Nothing else."))
    else:
        embed.add_field(name="📚 Books", inline=False, value=join_lines(_items_of(inv, ("book",)), empty="No books."))
        embed.add_field(name="🧪 Potions", inline=False, value=join_lines(_items_of(inv, ("potion",)), empty="No potions."))
    return embed


class InventoryView(BaseView):
    """The pages of an inventory: only the player who opened it changes the page."""

    def __init__(self, cog: "EconomyMiningCog", viewer_id: int, member: discord.abc.User, page: str = "overview"):
        super().__init__(allowed_ids={viewer_id}, timeout=300)
        self.cog, self.viewer_id, self.member = cog, viewer_id, member
        self.add_item(InventoryPageSelect(page))


class InventoryPageSelect(discord.ui.Select):
    view: InventoryView

    def __init__(self, current: str):
        options = [discord.SelectOption(label=name, value=key, emoji=emoji, default=key == current)
                   for key, (emoji, name) in INVENTORY_PAGES.items()]
        super().__init__(placeholder="Choose a page…", options=options)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        inv = await view.cog.bot.db.run(_inventory, view.member.id, view.viewer_id)
        page = self.values[0]
        new = InventoryView(view.cog, view.viewer_id, view.member, page)
        new.message = view.message
        view.stop()  # the old menu must not come back when it times out
        await interaction.response.edit_message(embed=inventory_embed(inv, view.member, page), view=new)


ORE_ICONS = {"gold": "🟨", "iron": "⬜", "diamond": "💎", "emerald": "💚"}  # when no custom emoji is set


def is_mining_channel(channel: discord.abc.GuildChannel | discord.Thread) -> bool:
    """channels.mining (and its threads); none set: every channel mines. Each player mines in their dimension."""
    mining_ids = channel_ids("mining")
    return not mining_ids or bool({channel.id, getattr(channel, "parent_id", None)} & mining_ids)


class EconomyMiningCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # user_id -> monotonic time when the user can mine again
        self._next_mine: dict[int, float] = {}
        # Spam channels have their own cooldown, so spamming there doesn't stop mining elsewhere.
        self._next_spam: dict[int, float] = {}

    async def spam_mine(self, user_id: int, now: float) -> None:
        if now < self._next_spam.get(user_id, 0.0):
            return
        self._next_spam[user_id] = now + mining.cooldown_seconds(0)
        await self.bot.db.run(mining.spam_mine, user_id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        if not self.bot.in_main_guild(message.guild.id):  # type: ignore[attr-defined]
            return  # Blocky only plays in its own server
        if message.channel.id in getattr(self.bot, "guide_channels", {}):
            return  # a private guide channel: nobody would see someone writing there just to mine

        user_id = message.author.id
        now = time.monotonic()
        channel = message.channel
        spam = channel_ids("spam")
        if spam and (channel.id in spam or getattr(channel, "parent_id", None) in spam):
            # No blocks, XP, drops or challenge progress here: only a tiny reward.
            return await self.spam_mine(user_id, now)
        if not is_mining_channel(channel):
            return  # not a mining channel: nothing
        if now < self._next_mine.get(user_id, 0.0):
            return
        # Reserve the slot before awaiting, so two quick messages can't both mine.
        self._next_mine[user_id] = now + 3600

        try:
            result = await self.bot.db.run(mining.mine, user_id)  # in the dimension they are in
        except Exception:
            self._next_mine.pop(user_id, None)
            raise
        self._next_mine[user_id] = now + result["cooldown"]
        self.bot.dispatch("blocky_mined", message, result)
        found = ([scrap_icon()] if result["scrap"] else []) + [EMOJI.get(o) or ORE_ICONS[o] for o in result["ores"]]
        for icon in found:  # Ancient debris and ores: rare enough to show
            try:
                await message.add_reaction(icon)
            except discord.HTTPException:
                pass

    @app_commands.command(name="inventory", description="Show your inventory, or another player's (everyone sees it).")
    @app_commands.describe(member="Whose inventory (empty = yours)")
    async def inventory(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        if member.bot:
            raise GameError("Bots don't have an inventory.")
        inv = await self.bot.db.run(_inventory, member.id, interaction.user.id)
        view = InventoryView(self, interaction.user.id, member)
        await interaction.response.send_message(embed=inventory_embed(inv, member, "overview"), view=view)
        view.message = await interaction.original_response()

    async def gear_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
        """The player's pieces with what each one sells for."""
        offers = await self.bot.db.run(shop.gear_offers, interaction.user.id)
        choices = []
        for g, offer in offers:
            name = f"{g['material']} {g['item']} ({g['durability']}/{g['max_durability']}) → {offer['price']:,} emeralds"
            if g["enchants"]:
                name += f" — {enchants.labels(g['enchants'])}"
            if g["equipped"]:
                name += " — equipped"
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name[:100], value=g["gear_id"]))
        return choices[:25]

    @app_commands.command(name="sell", description="Sell your blocks (all, one kind or an amount) or a piece of gear.")
    @app_commands.describe(block="Only this kind of block (empty = every kind)",
                           amount="How many (empty = all; more than you have = all you have)",
                           gear="Or a piece of gear: sold for part of its value, less when it's worn")
    @app_commands.choices(block=[app_commands.Choice(name=block_name(b), value=b) for b in BLOCK_TYPES])
    @app_commands.autocomplete(gear=gear_autocomplete)
    async def sell(self, interaction: discord.Interaction, block: str | None = None,
                   amount: app_commands.Range[int, 1] | None = None, gear: int | None = None):
        if gear is not None:
            if block is not None or amount is not None:
                raise GameError("Sell either blocks or a piece of gear, not both at once.")
            return await self.sell_gear(interaction, gear)
        res = await self.bot.db.run(players.sell_blocks, interaction.user.id, block, amount)

        lines = [
            f"{block_icon(b)} **{block_name(b)}** ×{amt} → +{em(amt * players.block_value(b))}"
            for b, amt in res["sold"].items()
        ]
        embed = discord.Embed(title="Sale complete", description="\n".join(lines), color=discord.Color.green())
        gained = res["base"] + res["bonus"]
        if res["bonus"]:
            why = ["Trader talent", "Villager", "Beacon"] + (["💰 Golden Hour"] if res["golden"] else []) \
                + ([f"biome {res['biome']:+.0%}"] if res.get("biome") else [])
            sign = "+" if res["bonus"] > 0 else "-"
            embed.add_field(name="Gained", value=f"{res['base']} {sign} {abs(res['bonus'])} ({', '.join(why)}) "
                                                 f"= {em(gained)}")
        else:
            embed.add_field(name="Gained", value=em(gained))
        embed.add_field(name="New balance", value=em(res["balance"]))
        if res["left"]:
            embed.add_field(name="Kept", value=" · ".join(f"{block_icon(b)} {b} ×{n:,}" for b, n in res["left"].items()),
                            inline=False)
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)  # public: rewards are shown to everyone

    async def sell_gear(self, interaction: discord.Interaction, gear_id: int) -> None:
        """Show the price of the piece; the player confirms before it is sold."""
        user = interaction.user
        piece = await self.bot.db.run(shop.owned_piece, user.id, gear_id)
        offer = await self.bot.db.run(shop.gear_offer, user.id, piece)
        rate = float(settings.get()["market"]["gear_sell_rate"])
        lines = [f"Sell {gear_label(piece)} for **{em(offer['price'])}**?",
                 f"Worth {em(offer['value'])} new (craft{' + books' if piece['enchants'] else ''}) × "
                 f"**{rate:.0%}** × **{offer['left']:.0%}** durability left"
                 + (f" + {em(offer['bonus'])} (Villager)" if offer["bonus"] else "") + "."]
        if piece["equipped"]:
            lines.append(f"⚠️ You're wearing it: your **{piece['item']}** slot will be empty.")
        if piece["enchants"]:
            lines.append("Its enchantments go with it.")

        async def do(confirm: discord.Interaction) -> None:
            res = await self.bot.db.run(shop.sell_gear, user.id, gear_id, offer["price"])
            await confirm.response.edit_message(content="Done.", view=None)
            embed = discord.Embed(title="Sale complete",
                                  description=f"{gear_label(res['piece'])} → +{em(res['price'])}",
                                  color=discord.Color.green())
            embed.add_field(name="New balance", value=em(res["balance"]))
            embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
            await confirm.followup.send(embed=embed)  # public, like the block sales

        await interaction.response.send_message("\n".join(lines), view=ConfirmView(user.id, "Sell", do), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyMiningCog(bot))
