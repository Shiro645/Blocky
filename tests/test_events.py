from __future__ import annotations

import random
import unittest

from game import events, gear, players, settings, shop
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2
HOUR = 3600


class DropTests(GameTestCase):
    overrides = {"challenges": {"per_week": 0}}  # keep challenge rewards out of the totals

    async def test_claim_each_reward_kind(self):
        await self.run_game(events.claim_drop, ALICE, {"reward": {"emeralds": 50}})
        await self.run_game(events.claim_drop, ALICE, {"reward": {"ingot": "iron", "amount": 3}})
        await self.run_game(events.claim_drop, ALICE, {"reward": {"block": "bedrock", "amount": 10}})
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 50)
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "iron"), 3)
        self.assertEqual((await self.run_game(players.get_blocks, ALICE))["bedrock"], 10)
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "drops_claimed"), 3)

    def test_roll_uses_the_table(self):
        settings.load()
        rng = random.Random(3)
        titles = {d["title"] for d in settings.get()["drops"]["table"]}
        self.assertTrue(all(events.roll_drop(rng)["title"] in titles for _ in range(50)))


class BossTests(GameTestCase):
    overrides = {"boss": {"hp": 30, "attack_cooldown_seconds": 60, "reward_pool": 100, "top_damage_bonus": 10, "crit_chance": 0}}

    async def test_only_one_active_boss(self):
        await self.run_game(events.spawn_boss)
        with self.assertRaises(GameError):
            await self.run_game(events.spawn_boss)

    async def test_attack_cooldown(self):
        await self.run_game(events.spawn_boss)
        await self.run_game(events.attack_boss, ALICE)
        with self.assertRaises(GameError):
            await self.run_game(events.attack_boss, ALICE)
        self.advance(60)
        await self.run_game(events.attack_boss, ALICE)

    async def test_defeat_shares_rewards_by_damage(self):
        boss = await self.run_game(events.spawn_boss)
        sword = await self.run_game(shop.create_gear, ALICE, "sword", "netherite")
        await self.run_game(gear.equip, ALICE, sword)
        await self.run_game(events.attack_boss, BOB)  # fists: ~1 damage

        defeat = None
        while defeat is None:
            res = await self.run_game(events.attack_boss, ALICE, boss["boss_id"])
            defeat = res["defeat"]
            self.advance(60)

        rewards = {r["user_id"]: r["reward"] for r in defeat["rewards"]}
        self.assertGreater(rewards[ALICE], rewards[BOB])
        self.assertLessEqual(sum(rewards.values()), 100 + 10)
        self.assertIsNone(await self.run_game(events.active_boss))
        self.assertEqual(await self.run_game(players.get_stat, BOB, "bosses_defeated"), 1)
        with self.assertRaises(GameError):
            await self.run_game(events.attack_boss, ALICE)

    async def test_boss_escapes(self):
        await self.run_game(events.spawn_boss)
        self.advance(25 * HOUR)
        escaped = await self.run_game(events.escape_expired)
        self.assertEqual(len(escaped), 1)
        self.assertIsNone(await self.run_game(events.active_boss))


if __name__ == "__main__":
    unittest.main()
