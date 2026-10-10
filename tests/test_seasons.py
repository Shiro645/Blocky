from __future__ import annotations

import unittest

from game import exchange, leaderboard, players, seasons
from tests.helpers import DAY, GameTestCase

ALICE, BOB, CAROL, DAVE = 1, 2, 3, 4


class SeasonTests(GameTestCase):
    async def test_only_earned_emeralds_count(self):
        await self.run_game(players.earn_emeralds, ALICE, 50)
        await self.run_game(players.give_emeralds, BOB, 500)
        await self.run_game(exchange.pay, BOB, ALICE, 100)
        overview = await self.run_game(seasons.overview, ALICE)
        self.assertEqual(overview["top"], [(ALICE, 50)])

    async def test_spending_does_not_lower_the_score(self):
        await self.run_game(players.earn_emeralds, ALICE, 50)
        await self.run_game(players.spend_emeralds, ALICE, 50)
        self.assertEqual((await self.run_game(seasons.overview, ALICE))["score"], 50)

    async def test_week_end_pays_podium_once(self):
        for uid, amount in ((ALICE, 10), (BOB, 40), (CAROL, 30), (DAVE, 20)):
            await self.run_game(players.earn_emeralds, uid, amount)
        self.assertEqual(await self.run_game(seasons.close_finished), [])  # week not over

        self.advance(7 * DAY)
        closed = await self.run_game(seasons.close_finished)
        self.assertEqual(len(closed), 1)
        podium = [(p["user_id"], p["reward"]) for p in closed[0]["podium"]]
        self.assertEqual(podium, [(BOB, 300), (CAROL, 150), (DAVE, 75)])
        # 40 + 300 for the season + 250 for the "Champion" achievement
        self.assertEqual(await self.run_game(players.get_emeralds, BOB), 590)
        self.assertEqual(await self.run_game(seasons.close_finished), [])  # not paid twice

        # Rewards don't feed the new season, and the champion is known.
        overview = await self.run_game(seasons.overview, BOB)
        self.assertEqual(overview["top"], [])
        self.assertEqual(overview["champion"], BOB)
        self.assertEqual(await self.run_game(players.get_stat, BOB, "seasons_won"), 1)
        self.assertTrue((await self.run_game(leaderboard.profile, BOB))["is_champion"])

    async def test_mined_blocks_are_scored_once(self):
        from game import exchange, mining

        res = await self.run_game(mining.mine, ALICE)
        value = players.block_value(res["block"]) * res["amount"]
        self.assertEqual((await self.run_game(seasons.overview, ALICE))["score"], value)
        # Giving the blocks to someone who sells them doesn't move the score.
        await self.run_game(exchange.trade, ALICE, BOB, f"block:{res['block']}", res["amount"], None, 0)
        await self.run_game(players.sell_all_blocks, BOB)
        self.assertEqual((await self.run_game(seasons.overview, BOB))["score"], 0)
        self.assertEqual((await self.run_game(seasons.overview, ALICE))["score"], value)

    async def test_season_end_is_next_monday(self):
        overview = await self.run_game(seasons.overview, ALICE)
        # START is Wednesday 12:00 -> Monday 00:00 is 4.5 days later.
        self.assertEqual(overview["ends_at"], int(self.now + 4.5 * DAY))

    async def test_season_leaderboard(self):
        await self.run_game(players.earn_emeralds, CAROL, 5)
        data = await self.run_game(leaderboard.leaderboard, "season", CAROL)
        self.assertEqual(data["rank"], 1)


if __name__ == "__main__":
    unittest.main()
