from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import assets, settings, villager
from utils.config import role_id
from utils.ui import asset_icon, em, report_error

log = logging.getLogger("villager")

TITLES = {"sell": "🛒 For sale", "buy": "💰 He buys", "exclusive": "✨ Exclusive"}


def offer_text(o: dict) -> str:
    text = f"{asset_icon(o['asset'])} **{assets.describe(o['asset'], o['amount'])}**\n".lstrip()
    if o["kind"] == "sell":
        off = round(float(settings.get()["villager"]["sell_discount"]) * 100)
        text += f"for **{em(o['price'])}** ~~{o['value']:,}~~ (-{off}%)"
    elif o["kind"] == "buy":
        text += f"he pays **{em(o['price'])}** (/sell: {o['value']:,})"
    else:
        text += f"for **{em(o['price'])}**, only sold here"
    if o["taken_by"] is not None:
        text += f"\n✅ Taken by <@{o['taken_by']}>"
    return text


def visit_embed(visit: dict) -> discord.Embed:
    here = visit["status"] == "here"
    if here:
        embed = discord.Embed(
            title="🧑‍🌾 The wandering villager is here!",
            description=(
                f"He leaves <t:{visit['leaves_at']}:R>. Each offer exists **once**: first come, first served."
            ),
            color=discord.Color.green(),
        )
    else:
        hour = int(settings.get()["villager"]["arrive_hour"])
        embed = discord.Embed(
            title="🧑‍🌾 The wandering villager has left",
            description=f"He comes back every day at {hour}:00.",
            color=discord.Color.dark_grey(),
        )
    for o in visit["offers"]:
        embed.add_field(name=TITLES[o["kind"]], value=offer_text(o), inline=True)
    return embed


class VillagerButton(discord.ui.DynamicItem[discord.ui.Button], template=r"blocky:villager:(?P<visit_id>\d+):(?P<slot>\d+)"):
    """Take an offer. Keeps working after a bot restart."""

    def __init__(self, visit_id: int, slot: int, label: str = "Take", emoji: str | None = None,
                 disabled: bool = False, style: discord.ButtonStyle = discord.ButtonStyle.success) -> None:
        super().__init__(
            discord.ui.Button(
                label=label, style=style, emoji=emoji or None, disabled=disabled,
                custom_id=f"blocky:villager:{visit_id}:{slot}",
            )
        )
        self.visit_id, self.slot = visit_id, slot

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["visit_id"]), int(match["slot"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: VillagerCog | None = interaction.client.get_cog("VillagerCog")  # type: ignore[assignment]
        if cog is None:
            return
        try:
            await cog.take(interaction, self.visit_id, self.slot)
        except Exception as error:
            await report_error(interaction, error)


def visit_view(visit: dict) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    here = visit["status"] == "here"
    for o in visit["offers"]:
        taken = o["taken_by"] is not None
        verb = "Sell" if o["kind"] == "buy" else "Buy"
        view.add_item(VillagerButton(
            visit["visit_id"], o["slot"],
            label="Taken" if taken else f"{verb} · {o['price']:,}",
            emoji=asset_icon(o["asset"]),
            disabled=taken or not here,
            style=discord.ButtonStyle.primary if o["kind"] == "exclusive" else discord.ButtonStyle.success,
        ))
    return view


class VillagerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._posting: set[int] = set()  # visits being posted (the loop and /event villager)

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(VillagerButton)
        self.villager_loop.start()

    async def cog_unload(self) -> None:
        self.villager_loop.cancel()
        self.bot.remove_dynamic_items(VillagerButton)

    # ---------- clock ----------
    @tasks.loop(minutes=1)
    async def villager_loop(self):
        try:
            for event in await self.bot.db.run(villager.tick):
                if event["type"] == "left":
                    await self.refresh(event["visit"])
            # Post the visit if it isn't posted yet (just arrived, or the channel was missing).
            visit = await self.bot.db.run(villager.current)
            if visit and not visit["message_id"]:
                await self.post(visit)
        except Exception:  # an error must never stop the loop
            log.exception("Villager loop failed")

    @villager_loop.before_loop
    async def before_villager_loop(self):
        await self.bot.wait_until_ready()

    # ---------- messages ----------
    async def post(self, visit: dict) -> None:
        channel = self.bot.announcer.channel("events") or self.bot.announcer.channel()
        if channel is None or visit["visit_id"] in self._posting:
            return
        self._posting.add(visit["visit_id"])
        try:
            fresh = await self.bot.db.run(villager.get_visit, visit["visit_id"])
            if fresh is None or fresh["message_id"]:
                return  # already posted
            visit = fresh
            rid = role_id("event_ping")
            msg = await channel.send(
                content=f"<@&{rid}>" if rid else None,
                embed=visit_embed(visit),
                view=visit_view(visit),
                # Only the configured role is pinged, never @everyone / @here.
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, users=False, roles=[discord.Object(rid)] if rid else False
                ),
            )
            await self.bot.db.run(villager.set_message, visit["visit_id"], msg.channel.id, msg.id)
        finally:
            self._posting.discard(visit["visit_id"])

    async def refresh(self, visit: dict) -> None:
        """Update the visit message (offers taken, departure)."""
        if not visit["channel_id"] or not visit["message_id"]:
            return
        channel = self.bot.get_channel(visit["channel_id"])
        if not isinstance(channel, discord.abc.Messageable):
            return
        try:
            await channel.get_partial_message(visit["message_id"]).edit(embed=visit_embed(visit), view=visit_view(visit))
        except discord.HTTPException:
            log.exception("Could not update the villager message")

    async def take(self, interaction: discord.Interaction, visit_id: int, slot: int) -> None:
        res = await self.bot.db.run(villager.take, interaction.user.id, visit_id, slot)
        await interaction.response.edit_message(embed=visit_embed(res["visit"]), view=visit_view(res["visit"]))
        o = res["offer"]
        what = f"{asset_icon(o['asset'])} **{assets.describe(o['asset'], o['amount'])}**".strip()
        if o["kind"] == "buy":
            text = f"✅ You sold {what} to the villager for **{em(o['price'])}**."
        else:
            text = f"✅ You bought {what} for **{em(o['price'])}**."
        await interaction.followup.send(text, ephemeral=True)

    # ---------- commands ----------
    @app_commands.command(name="villager", description="Is the wandering villager here? What does he offer?")
    async def villager_cmd(self, interaction: discord.Interaction):
        def load(ctx):
            return villager.current(ctx), villager.next_arrival(ctx)

        visit, next_at = await self.bot.db.run(load)
        if visit is None:
            return await interaction.response.send_message(
                f"🧑‍🌾 The villager isn't here. Next visit <t:{next_at}:F> (<t:{next_at}:R>).", ephemeral=True
            )
        embed = visit_embed(visit)
        if visit["channel_id"] and visit["message_id"] and interaction.guild:
            url = f"https://discord.com/channels/{interaction.guild.id}/{visit['channel_id']}/{visit['message_id']}"
            embed.description += f"\n[Go to his stall]({url}) to buy."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def staff_action(self, interaction: discord.Interaction, action: str) -> None:
        """/event villager (cogs/staff_events.py): make the villager come now, or leave."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        if action == "come":
            visit = await self.bot.db.run(villager.arrive)
            await self.post(visit)
            text = "The villager is here."
        else:
            visit = await self.bot.db.run(villager.leave_now)
            await self.refresh(visit)
            text = "The villager left."
        await interaction.followup.send(f"✅ {text}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VillagerCog(bot))
