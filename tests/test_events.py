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
