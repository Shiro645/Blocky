"""Dimensions (2.0.1): unlocking, mining per dimension, netherite as a goal, the gear rewind."""
from __future__ import annotations

from game import assets, dimensions, enchants, exchange, mining, players, rewind, settings, shop
from game.catalog import DIMENSION_BLOCKS, DIMENSIONS, rank_block
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2


def income(dimension: str) -> float:
    """Emeralds a mining reward is worth on average in a dimension, without gear or talents."""
    total = 0.0
    for amount in range(1, 7):
        weights = mining.pile_weights(amount, 0, 0, 1.0, dimension)
        total += amount * sum(w * players.block_value(b) for b, w in weights.items()) / sum(weights.values())
    return total / 6


def income_with_tools(dimension: str, tier: int) -> float:
    """The same with a pickaxe and a shovel of a tier (the exact expectation of mining.mine)."""
    g, v, m = settings.get()["gear"], players.block_value, dimensions.multiplier(dimension)
    common, second = rank_block(dimension, 0), rank_block(dimension, 1)
    up = g["pickaxe_upgrade_chance_per_tier"] * tier
    pick = g["pickaxe_extra_blocks_per_tier"] * tier * v("cobblestone") * m
    shovel = g["shovel_extra_gravel_per_tier"] * tier * v("gravel") * m
    total = 0.0
    for n in range(1, 7):
        weights = mining.pile_weights(n, 0, 0, 1.0, dimension)
        for b, w in weights.items():
            for block, chance in ((b, 1 - up), (mining.upgrade_block(b, dimension), up)):
                value = n * v(block) + pick
                if second == common:
                    ow = mining.pile_weights(n, 0, 0)
                    value += ow["gravel"] / sum(ow.values()) * shovel
                elif block == second:
                    value += shovel
                total += w / sum(weights.values()) * chance * value / 6
    return total


class DimensionTests(GameTestCase):
    def test_each_dimension_pays_more(self):
        base = income("overworld")
        self.assertAlmostEqual(base, 5.23, places=2)  # the dirt didn't change the overworld
        ratios = [round(income(d) / base, 2) for d in DIMENSIONS]
        self.assertEqual(ratios, [1.0, 1.25, 1.5, 1.77, 2.01])

    def test_tools_keep_the_ratios(self):
        for tier in range(1, 5):  # gold to netherite tools
            base = income_with_tools("overworld", tier)
            for d, target in zip(DIMENSIONS, (1.0, 1.25, 1.5, 1.75, 2.0)):
                self.assertAlmostEqual(income_with_tools(d, tier) / base, target, delta=0.07, msg=(d, tier))

    async def test_locked_until_the_staff_unlocks(self):
        with self.assertRaisesRegex(GameError, "haven't unlocked"):
            await self.run_game(mining.mine, ALICE, "nether")
        res = await self.run_game(dimensions.set_highest, ALICE, "end")
        self.assertEqual(res["unlocked"], ["overworld", "nether", "end"])
        for _ in range(30):
            got = await self.run_game(mining.mine, ALICE, "nether")
            self.assertIn(got["block"], DIMENSION_BLOCKS["nether"])
            self.assertEqual(got["bonus_block"], "netherrack")
        await self.run_game(mining.mine, ALICE, "end")
        with self.assertRaises(GameError):
            await self.run_game(mining.mine, ALICE, "deep_dark")
        await self.run_game(dimensions.set_highest, ALICE, "overworld")  # the staff can lock them again
        with self.assertRaises(GameError):
            await self.run_game(mining.mine, ALICE, "nether")

    async def test_the_upgrade_stays_in_the_dimension(self):
        self.assertEqual(mining.upgrade_block("gravel"), "deepslate")
        self.assertEqual(mining.upgrade_block("nether_bricks", "nether"), "gilded_blackstone")
        self.assertEqual(mining.upgrade_block("shimmer_stone", "shimmer"), "shimmer_stone")

    async def test_scraps_only_from_the_nether(self):
        settings.load({"dimensions": {"scrap_chance": 1.0}})
        await self.run_game(dimensions.set_highest, ALICE, "nether")
        self.assertEqual((await self.run_game(mining.mine, ALICE, "overworld"))["scrap"], 0)
        self.assertEqual((await self.run_game(mining.mine, ALICE, "nether"))["scrap"], 1)
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "scrap", "none"), 1)


class NetheriteTests(GameTestCase):
    async def test_not_at_the_market(self):
        self.assertNotIn("netherite_ingot", shop.market_offers())
        with self.assertRaises(GameError):
            await self.run_game(shop.buy, ALICE, "netherite_ingot", 1)

    async def test_ingot_from_scraps_and_gold(self):
        await self.run_game(players.add_item, ALICE, "scrap", "none", 3)
        await self.run_game(players.add_item, ALICE, "ingot", "gold", 4)
        with self.assertRaisesRegex(GameError, "1 netherite scrap"):
            await self.run_game(shop.craft, ALICE, "netherite_ingot")
        await self.run_game(players.add_item, ALICE, "scrap", "none", 1)
        res = await self.run_game(shop.craft, ALICE, "netherite_ingot")
        self.assertEqual(res["have"], 1)
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "scrap", "none"), 0)
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "gold"), 0)

    async def test_upgrade_a_diamond_piece(self):
        with self.assertRaisesRegex(GameError, "no diamond sword"):
            await self.run_game(shop.craft, ALICE, "sword", "netherite")
        spare = await self.run_game(shop.create_gear, ALICE, "sword", "diamond")
        worn = await self.run_game(shop.create_gear, ALICE, "sword", "diamond")
        await self.run_game(enchants.set_enchants, worn, {"sharpness": 2})
        from game import gear

        await self.run_game(gear.equip, ALICE, worn)
        with self.assertRaisesRegex(GameError, "1 netherite ingot"):
            await self.run_game(shop.craft, ALICE, "sword", "netherite")
        await self.run_game(players.add_item, ALICE, "ingot", "netherite", 1)
        res = await self.run_game(shop.craft, ALICE, "sword", "netherite")
        self.assertEqual(res["gear_id"], worn)  # the worn piece goes first
        piece = await self.run_game(shop.owned_piece, ALICE, worn)
        self.assertEqual((piece["material"], piece["durability"], piece["enchants"]),
                         ("netherite", shop.max_durability("netherite", "sword"), {"sharpness": 2}))
        self.assertEqual((await self.run_game(shop.owned_piece, ALICE, spare))["material"], "diamond")
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "netherite"), 0)

    async def test_never_traded(self):
        await self.run_game(players.add_item, ALICE, "ingot", "netherite", 2)
        await self.run_game(players.add_item, ALICE, "scrap", "none", 2)
        gid = await self.run_game(shop.create_gear, ALICE, "helmet", "netherite")
        piece = await self.run_game(shop.owned_piece, ALICE, gid)
        for key in ("ingot:netherite", "scrap", assets.gear_key(piece)):
            self.assertFalse(assets.tradeable(key))
            with self.assertRaisesRegex(GameError, "can't be traded"):
                await self.run_game(exchange.trade, ALICE, BOB, key, 1, None, 0)
            with self.assertRaisesRegex(GameError, "can't be traded"):
                await self.run_game(exchange.list_for_sale, ALICE, key, 1, 100)
        self.assertTrue(assets.tradeable("ingot:diamond"))

    def test_no_netherite_reward_in_the_settings(self):
        self.assertTrue(settings.problems({"villager": {"goods": [{"asset": "ingot:netherite", "amount": 1}]}}))
        self.assertTrue(settings.problems({"drops": {"table": [
            {"weight": 1, "title": "Debris", "reward": {"ingot": "netherite", "amount": 1}}]}}))
        self.assertTrue(settings.problems({"daily": {"weekly_bonus_item": "netherite"}}))


class RewindTests(GameTestCase):
    async def test_everything_paid_back(self):
        sword = await self.run_game(shop.create_gear, ALICE, "sword", "netherite")  # crafted before: 2 ingots + 1 stick
        await self.run_game(enchants.set_enchants, sword, {"sharpness": 2})
        await self.run_game(shop.create_gear, ALICE, "shield", "iron")
        await self.run_game(players.add_item, ALICE, "ingot", "netherite", 3)
        await self.run_game(players.add_item, ALICE, "ingot", "diamond", 5)  # kept
        listed = await self.run_game(shop.create_gear, BOB, "pickaxe", "iron")
        piece = await self.run_game(shop.owned_piece, BOB, listed)
        await self.run_game(players.add_item, BOB, "lapis", "none", 4)
        await self.run_game(exchange.list_for_sale, BOB, assets.gear_key(piece), 1, 999)
        await self.run_game(exchange.list_for_sale, BOB, "lapis", 4, 50)  # stays listed

        plan = await self.run_game(rewind.plan)
        sword_value = round(2 * 300 + 0.25 + 150)
        self.assertEqual(plan[ALICE], {"pieces": 2, "ingots": 3, "listings": 0,
                                       "emeralds": sword_value + 60 + 3 * 300})
        self.assertEqual(plan[BOB], {"pieces": 0, "ingots": 0, "listings": 1, "emeralds": round(3 * 10 + 0.5)})

        await self.run_game(rewind.apply)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), plan[ALICE]["emeralds"])
        self.assertEqual(await self.run_game(players.get_emeralds, BOB), plan[BOB]["emeralds"])
        self.assertEqual(await self.run_game(shop.get_gear, ALICE), [])
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "netherite"), 0)
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "diamond"), 5)
        left = await self.run_game(exchange.listings_of, BOB)
        self.assertEqual([r["asset"] for r in left], ["lapis"])
        with self.assertRaisesRegex(GameError, "already done"):  # once only
            await self.run_game(rewind.plan)
