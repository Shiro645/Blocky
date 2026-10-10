from __future__ import annotations

import asyncio
import random
import unittest

from game import gear, mining, players, settings, shop
from game.errors import GameError
from game.notices import LevelUp
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2


class TransactionTests(GameTestCase):
    async def test_error_rolls_back_everything(self):
        def failing(ctx):
            players.give_emeralds(ctx, ALICE, 100)
            raise GameError("nope")

        with self.assertRaises(GameError):
            await self.run_game(failing)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 0)

    async def test_concurrent_purchases_cannot_double_spend(self):
        await self.run_game(players.give_emeralds, ALICE, 10)
        results = await asyncio.gather(
            self.db.run(shop.buy, ALICE, "iron_ingot", 1),
            self.db.run(shop.buy, ALICE, "iron_ingot", 1),
            return_exceptions=True,
        )
        self.assertEqual(sum(isinstance(r, GameError) for r in results), 1)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 0)
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "iron"), 1)


class LegacyDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_database_is_set_aside(self):
        import sqlite3
        import tempfile
        from pathlib import Path

        from game.db import Database

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "economy.db"
            old = sqlite3.connect(path)
            old.execute("CREATE TABLE users (user_id INTEGER PRIMARY KEY, emeralds INTEGER);")
            old.commit()
            old.close()

            db = Database(path)
            await db.open()
            await db.run(players.give_emeralds, ALICE, 5)
            await db.close()

            backups = [p.name for p in Path(tmp).iterdir() if ".legacy-" in p.name]
            self.assertEqual(len(backups), 1)

            db = Database(path)  # reopening the new database keeps it
            await db.open()
            self.assertEqual(await db.run(players.get_emeralds, ALICE), 5)
            await db.close()


class EconomyTests(GameTestCase):
    async def test_sell_all_blocks_with_trader_bonus(self):
        def setup(ctx):
            players.add_blocks(ctx, ALICE, "cobblestone", 10)  # 10
            players.add_blocks(ctx, ALICE, "bedrock", 2)  # 20
            ctx.execute("UPDATE users SET trader_points=5 WHERE user_id=?;", (ALICE,))

        await self.run_game(setup)
        res = await self.run_game(players.sell_all_blocks, ALICE)
        self.assertEqual(res["base"], 30)
        self.assertEqual(res["bonus"], 3)  # +10%
        self.assertEqual(res["balance"], 33)
        # Blocks are scored when mined (these were given): only the trader bonus is earned.
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "emeralds_earned"), 3)

    async def test_sell_nothing_is_an_error(self):
        with self.assertRaises(GameError):
            await self.run_game(players.sell_all_blocks, ALICE)

    async def test_buy_requires_emeralds(self):
        with self.assertRaises(GameError):
            await self.run_game(shop.buy, ALICE, "diamond_ingot", 1)
        await self.run_game(players.give_emeralds, ALICE, 3)
        res = await self.run_game(shop.buy, ALICE, "sticks", 3)
        self.assertEqual(res["amount"], 12)
        self.assertEqual(res["balance"], 0)

    async def test_craft_consumes_resources_and_creates_gear(self):
        def setup(ctx):
            players.add_item(ctx, ALICE, "ingot", "iron", 3)
            players.add_item(ctx, ALICE, "stick", "none", 1)

        await self.run_game(setup)
        with self.assertRaises(GameError):
            await self.run_game(shop.craft, ALICE, "pickaxe", "iron")  # needs 2 sticks
        await self.run_game(shop.craft, ALICE, "sword", "iron")
        gear = await self.run_game(shop.get_gear, ALICE)
        self.assertEqual(len(gear), 1)
        self.assertEqual((gear[0]["item"], gear[0]["material"]), ("sword", "iron"))
        self.assertEqual(gear[0]["durability"], gear[0]["max_durability"])
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "iron"), 1)
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "stick", "none"), 0)


class ProgressionTests(GameTestCase):
    async def test_level_up_gives_talent_points_and_notice(self):
        # levels 1->5 need 100+125+150+175 = 550 XP
        p = await self.run_game(players.add_xp, ALICE, 550)
        self.assertEqual(p["level"], 5)
        self.assertEqual(p["talent_points"], 1)
        self.assertEqual(self.notices, [LevelUp(ALICE, 1, 5, 1)])

    async def test_set_level_recomputes_talent_points(self):
        await self.run_game(players.set_level, ALICE, 20)  # 4 points
        await self.run_game(players.buy_talent, ALICE, "miner", 3)
        p = await self.run_game(players.set_level, ALICE, 10)  # earned 2, spent 3
        self.assertEqual(p["talent_points"], 0)
        p = await self.run_game(players.set_level, ALICE, 30)  # earned 6, spent 3
        self.assertEqual(p["talent_points"], 3)

    async def test_talent_caps(self):
        await self.run_game(players.add_talent_points, ALICE, 20)
        with self.assertRaises(GameError):
            await self.run_game(players.buy_talent, ALICE, "lucky", 6)
        p = await self.run_game(players.buy_talent, ALICE, "lucky", 5)
        self.assertEqual(p["lucky_points"], 5)

    async def test_reset_refunds_points(self):
        await self.run_game(players.add_talent_points, ALICE, 4)
        await self.run_game(players.buy_talent, ALICE, "trader", 3)
        p = await self.run_game(players.reset_talents, ALICE)
        self.assertEqual(p["talent_points"], 4)
        self.assertEqual(p["trader_points"], 0)


class MiningTests(GameTestCase):
    async def test_mine_adds_blocks_xp_and_stats(self):
        res = await self.run_game(mining.mine, ALICE)
        blocks = await self.run_game(players.get_blocks, ALICE)
        self.assertEqual(blocks[res["block"]], res["amount"])
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "blocks_mined"), res["amount"])
        self.assertEqual((await self.run_game(players.get_user, ALICE))["xp"], res["xp"])
        self.assertEqual(res["cooldown"], 30)

    def test_cooldown_floor(self):
        self.assertEqual(mining.cooldown_seconds(0), 30)
        self.assertEqual(mining.cooldown_seconds(5), 20)
        self.assertEqual(mining.cooldown_seconds(99), 10)  # capped at 10 points

    def test_roll_blocks_ranges(self):
        rng = random.Random(0)
        for _ in range(500):
            block, amount = mining.roll_blocks(rng, 8, 5)
            self.assertIn(block, ("cobblestone", "gravel", "deepslate", "obsidian", "bedrock"))
            self.assertTrue(1 <= amount <= 7)



class BalanceTests(GameTestCase):
    async def test_spam_channel_reward_adds_up(self):
        settings.load({"mining": {"spam_reward": 0.25}})
        got = [await self.run_game(mining.spam_mine, ALICE) for _ in range(8)]
        self.assertEqual(got, [0, 0, 0, 1, 0, 0, 0, 1])
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 2)
        blocks = await self.run_game(players.get_blocks, ALICE)
        self.assertEqual(sum(blocks.values()), 0)  # no blocks in spam channels

    async def test_default_spam_reward_is_tiny(self):
        got = sum([await self.run_game(mining.spam_mine, ALICE) for _ in range(99)])
        self.assertEqual(got, 0)
        self.assertEqual(await self.run_game(mining.spam_mine, ALICE), 1)  # the 100th message

    async def test_pickaxe_bonus_is_cobblestone(self):
        gid = await self.run_game(shop.create_gear, ALICE, "pickaxe", "netherite")
        await self.run_game(gear.equip, ALICE, gid)
        seen = set()
        for seed in range(60):
            self.db.rng = random.Random(seed)
            before = await self.run_game(players.get_blocks, ALICE)
            res = await self.run_game(mining.mine, ALICE)
            after = await self.run_game(players.get_blocks, ALICE)
            self.assertEqual(res["bonus"], 4)  # netherite = tier 4
            if res["block"] != "cobblestone":
                self.assertEqual(after[res["block"]] - before[res["block"]], res["amount"])
                self.assertEqual(after["cobblestone"] - before["cobblestone"], 4)
                seen.add(res["block"])
        self.assertTrue(seen)

    async def test_repair(self):
        gid = await self.run_game(shop.create_gear, ALICE, "sword", "iron")  # crafting value 20.25
        await self.run_game(lambda ctx: ctx.execute("UPDATE gear SET durability = max_durability / 2 WHERE gear_id=?;", (gid,)))
        with self.assertRaisesRegex(GameError, "Not enough emeralds"):
            await self.run_game(shop.repair, ALICE, gid)
        await self.run_game(players.give_emeralds, ALICE, 100)
        res = await self.run_game(shop.repair, ALICE, gid)
        self.assertEqual(res["cost"], 7)  # 60% of 20.25 for half the durability, rounded up
        piece = (await self.run_game(shop.get_gear, ALICE))[0]
        self.assertEqual(piece["durability"], piece["max_durability"])
        with self.assertRaisesRegex(GameError, "full durability"):
            await self.run_game(shop.repair, ALICE, gid)


if __name__ == "__main__":
    unittest.main()
