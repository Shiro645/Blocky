from __future__ import annotations

import unittest

from game import leaderboard, players, shop
from tests.helpers import GameTestCase

ALICE, BOB, CAROL = 1, 2, 3


class LeaderboardTests(GameTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()

        def setup(ctx):
            players.give_emeralds(ctx, ALICE, 100)
            players.give_emeralds(ctx, BOB, 50)
            players.add_blocks(ctx, BOB, "bedrock", 10)  # +100 fortune
            players.add_item(ctx, CAROL, "ingot", "diamond", 1)  # +25 fortune
            players.bump_stat(ctx, CAROL, "blocks_mined", 7)

        await self.run_game(setup)

    async def test_emeralds_board(self):
        data = await self.run_game(leaderboard.leaderboard, "emeralds", BOB)
        self.assertEqual(data["top"], [(ALICE, 100), (BOB, 50)])
        self.assertEqual(data["rank"], 2)

    async def test_fortune_counts_inventory(self):
        data = await self.run_game(leaderboard.leaderboard, "fortune", CAROL)
        self.assertEqual(data["top"], [(BOB, 150), (ALICE, 100), (CAROL, 25)])
        self.assertEqual(data["rank"], 3)

    async def test_worn_gear_is_worth_less(self):
        def setup(ctx):
            gid = shop.create_gear(ctx, CAROL, "helmet", "iron")  # 5 iron = 50
            ctx.execute("UPDATE gear SET durability = max_durability / 2 WHERE gear_id=?;", (gid,))

        await self.run_game(setup)
        fortunes = await self.run_game(leaderboard.fortunes)
        self.assertEqual(fortunes[CAROL], 25 + 25)

    async def test_stat_board_and_unranked_player(self):
        data = await self.run_game(leaderboard.leaderboard, "blocks_mined", ALICE)
        self.assertEqual(data["top"], [(CAROL, 7)])
        self.assertIsNone(data["rank"])

    async def test_profile(self):
        p = await self.run_game(leaderboard.profile, BOB)
        self.assertEqual(p["fortune"], 150)
        self.assertEqual(p["fortune_rank"], 1)


if __name__ == "__main__":
    unittest.main()
