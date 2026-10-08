from __future__ import annotations

import random
import time
import discord
from discord import app_commands
from discord.ext import commands

from utils.config import load_config
from database import (
    init_db,
    ensure_user,
    add_blocks,
    get_blocks,
    get_items,
    get_gear,
    get_emeralds,
    sell_all_blocks,
    add_xp,
    get_progress,
    add_emeralds,
)

from utils.config import load_emojis

EMOJI = load_emojis()

BLOCK_VALUES = {
    "cobblestone": 1,
    "gravel": 3,
    "deepslate": 5,
    "bedrock": 10,
}

def _effective_cooldown_seconds(base: int, efficiency_points: int) -> int:
    if base <= 0:
        return 0
    return max(5, base - 2 * max(0, efficiency_points))

def generate_blocks(miner_points: int, lucky_points: int) -> tuple[str, int]:
    amount = random.randint(1, 6)
    miner = max(0, miner_points)
    lucky = max(0, lucky_points)

    if amount == 6:
        return "cobblestone", amount

    if amount in (4, 5):
        weights = [70, 30 + min(40, miner * 5)]
        block = random.choices(["cobblestone", "gravel"], weights=weights, k=1)[0]
        return block, amount

    if amount in (2, 3):
        block = random.choices(
            ["cobblestone", "gravel", "deepslate"],
            weights=[70, 20 + min(30, miner * 3), 10 + min(30, miner * 2)],
            k=1,
        )[0]
        return block, amount

    bedrock_w = 1 + min(5, lucky)  # 1..6
    block = random.choices(
        ["cobblestone", "gravel", "deepslate", "bedrock"],
        weights=[70, 20, 9, bedrock_w],
        k=1,
    )[0]
    return block, amount

def maybe_bonus_block(base_amount: int, miner_points: int) -> int:
    if base_amount < 4:
        return base_amount
    chance = min(0.25, 0.05 * max(0, miner_points))
    return base_amount + (1 if random.random() < chance else 0)

def trader_sell_bonus_multiplier(trader_points: int) -> float:
    return 1.0 + min(0.20, 0.02 * max(0, trader_points))

class EconomyPhase1Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()
        self._last_gain_ts: dict[int, float] = {}

    def _base_cooldown_seconds(self) -> int:
        cfg = load_config()
        eco = cfg.get("economy", {})
        try:
            return max(0, int(eco.get("cooldown_seconds", 30)))
        except Exception:
            return 30

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None:
            return
        if message.author.bot:
            return

        user_id = message.author.id
        ensure_user(user_id)

        p = get_progress(user_id)
        cooldown = _effective_cooldown_seconds(self._base_cooldown_seconds(), p["efficiency_points"])
        now = time.monotonic()

        if cooldown > 0:
            last = self._last_gain_ts.get(user_id, 0.0)
            if now - last < cooldown:
                return
            self._last_gain_ts[user_id] = now

        block_type, amount = generate_blocks(p["miner_points"], p["lucky_points"])
        amount = maybe_bonus_block(amount, p["miner_points"])
        add_blocks(user_id, block_type, amount)

        xp_gain = random.randint(5, 15)
        add_xp(user_id, xp_gain)

    @app_commands.command(name="inventory", description="Show your blocks, emeralds and items.")
    async def inventory(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        ensure_user(user_id)

        blocks = get_blocks(user_id)
        items = get_items(user_id)
        gear = get_gear(user_id)
        emeralds = get_emeralds(user_id)

        lines = []
        total_value = 0
        for block_type, amt in blocks.items():
            value_each = BLOCK_VALUES.get(block_type, 0)
            total_value += amt * value_each
            lines.append(f"- **{block_type}**: {amt} (value: {value_each} {EMOJI['emerald']} each)")

        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Inventory",
            description="\n".join(lines) if lines else "No blocks yet.",
        )

        embed.add_field(name=f"{EMOJI['emerald']} Emeralds", value=str(emeralds), inline=True)
        embed.add_field(name="Estimated block sell value", value=f"{total_value} {EMOJI['emerald']}", inline=True)

        if items:
            item_lines = []
            for (item, material), amt in sorted(items.items()):
                prefix = ""
                if item == "stick":
                    prefix = f"{EMOJI['stick']} "
                else:
                    prefix = (EMOJI.get(material, "") + " ") if EMOJI.get(material) else ""
                if material == "none":
                    item_lines.append(f"- {prefix}**{item}**: {amt}")
                else:
                    item_lines.append(f"- {prefix}**{material} {item}**: {amt}")
            embed.add_field(name="Items", value="\n".join(item_lines)[:1024], inline=False)
        else:
            embed.add_field(name="Items", value="No items yet.", inline=False)

        if gear:
            gear_lines = []
            for g_item, g_material in gear:
                prefix = EMOJI.get(g_material, "")
                gear_lines.append(f"- {prefix} **{g_material} {g_item}**")
            embed.add_field(name="Gear", value="\n".join(gear_lines)[:1024], inline=False)
        else:
            embed.add_field(name="Gear", value="No gear yet.", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="sell", description="Sell all your blocks for emeralds.")
    async def sell(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        ensure_user(user_id)

        p = get_progress(user_id)
        gained, sold = sell_all_blocks(user_id)
        if gained == 0:
            return await interaction.response.send_message("You have no blocks to sell.", ephemeral=True)

        mult = trader_sell_bonus_multiplier(p["trader_points"])
        bonus = int(round(gained * (mult - 1.0)))
        if bonus > 0:
            add_emeralds(user_id, bonus)

        new_emeralds = get_emeralds(user_id)

        sold_lines = []
        for b, amt in sold.items():
            sold_lines.append(f"- **{b}** x{amt} → +{amt * BLOCK_VALUES[b]} {EMOJI['emerald']}")

        embed = discord.Embed(title="Sale complete", description="\n".join(sold_lines))
        if bonus > 0:
            embed.add_field(name=f"{EMOJI['emerald']} Gained", value=f"{gained} + {bonus} bonus = {gained + bonus}", inline=True)
        else:
            embed.add_field(name=f"{EMOJI['emerald']} Gained", value=str(gained), inline=True)
        embed.add_field(name=f"{EMOJI['emerald']} New balance", value=str(new_emeralds), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyPhase1Cog(bot))
