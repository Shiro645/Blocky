from __future__ import annotations

import unittest

from game import assets, daily, exchange, players, shop
from game.errors import GameError
from tests.helpers import DAY, GameTestCase

ALICE, BOB = 1, 2


class DailyTests(GameTestCase):
    async def test_streak_grows_and_resets(self):
        first = await self.run_game(daily.claim, ALICE)
        self.assertEqual((first["streak"], first["emeralds"]), (1, 30))
        with self.assertRaises(GameError):
            await self.run_game(daily.claim, ALICE)

        self.advance(DAY)
        second = await self.run_game(daily.claim, ALICE)
        self.assertEqual((second["streak"], second["emeralds"]), (2, 40))

        self.advance(2 * DAY)  # missed a day
        third = await self.run_game(daily.claim, ALICE)
        self.assertEqual(third["streak"], 1)
        self.assertEqual(third["lost_streak"], 2)
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "best_streak"), 2)

    async def test_seventh_day_bonus_and_cap(self):
        for day in range(1, 9):
            res = await self.run_game(daily.claim, ALICE)
            self.advance(DAY)
        self.assertEqual(res["streak"], 8)
        self.assertEqual(res["emeralds"], 30 + 10 * 6)  # capped at 7 days
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "diamond"), 1)

    async def test_daily_counts_as_earned(self):
        await self.run_game(daily.claim, ALICE)
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "emeralds_earned"), 30)


class PayTests(GameTestCase):
    async def test_pay_moves_emeralds_without_counting_as_earned(self):
        await self.run_game(players.give_emeralds, ALICE, 100)
        await self.run_game(exchange.pay, ALICE, BOB, 40)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 60)
        self.assertEqual(await self.run_game(players.get_emeralds, BOB), 40)
        self.assertEqual(await self.run_game(players.get_stat, BOB, "emeralds_earned"), 0)

    async def test_pay_rules(self):
        await self.run_game(players.give_emeralds, ALICE, 10)
        for args in ((ALICE, ALICE, 5), (ALICE, BOB, 0), (ALICE, BOB, 11)):
            with self.assertRaises(GameError):
                await self.run_game(exchange.pay, *args)


class TradeTests(GameTestCase):
    async def test_swap_ingots_for_gear_keeps_durability(self):
        def setup(ctx):
            players.add_item(ctx, ALICE, "ingot", "iron", 5)
            gid = shop.create_gear(ctx, BOB, "sword", "diamond")
            ctx.execute("UPDATE gear SET durability=10, equipped=1 WHERE gear_id=?;", (gid,))

        await self.run_game(setup)
        await self.run_game(exchange.trade, ALICE, BOB, "ingot:iron", 5, "gear:diamond:sword", 1)
        alice_gear = await self.run_game(shop.get_gear, ALICE)
        self.assertEqual(len(alice_gear), 1)
        self.assertEqual(alice_gear[0]["durability"], 10)
        self.assertEqual(alice_gear[0]["equipped"], 0)
        self.assertEqual(await self.run_game(shop.get_gear, BOB), [])
        self.assertEqual(await self.run_game(players.item_amount, BOB, "ingot", "iron"), 5)

    async def test_trade_fails_atomically(self):
        await self.run_game(players.add_item, ALICE, "ingot", "iron", 5)
        with self.assertRaises(GameError):
            await self.run_game(exchange.trade, ALICE, BOB, "ingot:iron", 5, "emeralds", 10)
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "iron"), 5)

    async def test_gift(self):
        await self.run_game(players.add_blocks, ALICE, "bedrock", 3)
        await self.run_game(exchange.trade, ALICE, BOB, "block:bedrock", 2, None, 0)
        self.assertEqual((await self.run_game(players.get_blocks, BOB))["bedrock"], 2)


class AuctionTests(GameTestCase):
    async def test_sell_buy_with_tax(self):
        await self.run_game(players.add_item, ALICE, "ingot", "diamond", 4)
        await self.run_game(players.give_emeralds, BOB, 100)
        listing = await self.run_game(exchange.list_for_sale, ALICE, "ingot:diamond", 4, 100)
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "diamond"), 0)

        with self.assertRaises(GameError):
            await self.run_game(exchange.buy, ALICE, listing["auction_id"])
        res = await self.run_game(exchange.buy, BOB, listing["auction_id"])
        self.assertEqual(res["tax"], 5)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 95)
        self.assertEqual(await self.run_game(players.get_emeralds, BOB), 0)
        self.assertEqual(await self.run_game(players.item_amount, BOB, "ingot", "diamond"), 4)
        with self.assertRaises(GameError):
            await self.run_game(exchange.buy, BOB, listing["auction_id"])

    async def test_cancel_and_expire_return_items(self):
        gid = await self.run_game(shop.create_gear, ALICE, "boots", "iron")
        await self.run_game(lambda ctx: ctx.execute("UPDATE gear SET durability=7 WHERE gear_id=?;", (gid,)))
        first = await self.run_game(exchange.list_for_sale, ALICE, "gear:iron:boots", 1, 30)
        with self.assertRaises(GameError):
            await self.run_game(exchange.cancel, BOB, first["auction_id"])
        await self.run_game(exchange.cancel, ALICE, first["auction_id"])
        self.assertEqual((await self.run_game(shop.get_gear, ALICE))[0]["durability"], 7)

        await self.run_game(exchange.list_for_sale, ALICE, "gear:iron:boots", 1, 30)
        self.advance(8 * DAY)
        expired = await self.run_game(exchange.expire)
        self.assertEqual(len(expired), 1)
        self.assertEqual(len(await self.run_game(shop.get_gear, ALICE)), 1)

    async def test_listing_limit(self):
        await self.run_game(players.add_blocks, ALICE, "gravel", 20)
        for _ in range(10):
            await self.run_game(exchange.list_for_sale, ALICE, "block:gravel", 1, 5)
        with self.assertRaises(GameError):
            await self.run_game(exchange.list_for_sale, ALICE, "block:gravel", 1, 5)

    async def test_browse_search_and_pages(self):
        await self.run_game(players.add_blocks, ALICE, "gravel", 20)
        await self.run_game(players.add_item, ALICE, "stick", "none", 3)
        for _ in range(9):
            await self.run_game(exchange.list_for_sale, ALICE, "block:gravel", 1, 5)
        await self.run_game(exchange.list_for_sale, ALICE, "stick", 3, 5)
        page = await self.run_game(exchange.browse, "stick")
        self.assertEqual(page["total"], 1)
        page = await self.run_game(exchange.browse, "", 1, 4)
        self.assertEqual(page["pages"], 3)


class AssetTests(GameTestCase):
    async def test_owned_lists_everything(self):
        def setup(ctx):
            players.give_emeralds(ctx, ALICE, 3)
            players.add_blocks(ctx, ALICE, "gravel", 2)
            players.add_item(ctx, ALICE, "stick", "none", 4)
            shop.create_gear(ctx, ALICE, "axe", "gold")
            shop.create_gear(ctx, ALICE, "axe", "gold")

        await self.run_game(setup)
        owned = dict(await self.run_game(assets.owned, ALICE))
        self.assertEqual(owned, {"emeralds": 3, "block:gravel": 2, "stick": 4, "gear:gold:axe": 2})

    def test_parse_rejects_garbage(self):
        for key in ("gold", "ingot:wood", "gear:iron", "block:dirt", "emeralds:1"):
            with self.assertRaises(GameError):
                assets.parse(key)


if __name__ == "__main__":
    unittest.main()
