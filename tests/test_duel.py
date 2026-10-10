from __future__ import annotations

import random
import unittest

from game import duel, gear, players, seasons, settings, shop
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2


class SimulateTests(unittest.TestCase):
    def setUp(self):
        settings.load()

    def test_better_gear_wins_most_fights(self):
        rng = random.Random(42)
        wins = 0
        for _ in range(200):
            strong = duel.Fighter(ALICE, attack=8, reduction=0.6, hp=20)
            weak = duel.Fighter(BOB, attack=1, reduction=0, hp=20)
            wins += duel.simulate(rng, strong, weak).winner == 0
        self.assertGreater(wins, 190)

    def test_equal_fighters_are_balanced(self):
        rng = random.Random(7)
        wins = sum(
            duel.simulate(rng, duel.Fighter(1, 6, 0.3, 20), duel.Fighter(2, 6, 0.3, 20)).winner == 0
            for _ in range(400)
        )
        self.assertTrue(140 < wins < 260)

    def test_fight_always_ends(self):
        rng = random.Random(1)
        res = duel.simulate(rng, duel.Fighter(1, 1, 0.8, 20), duel.Fighter(2, 1, 0.8, 20))
        self.assertLessEqual(len(res.fight.log), settings.get()["duel"]["max_rounds"])
        self.assertIn(res.winner, (0, 1))


class FightTests(GameTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.run_game(players.give_emeralds, ALICE, 100)
        await self.run_game(players.give_emeralds, BOB, 100)

    async def test_winner_takes_the_pot(self):
        res = await self.run_game(duel.fight, ALICE, BOB, 50)
        winner, loser = res["winner"], res["loser"]
        # 100 - 50 + 100 from the pot + 20 for the "First Blood" achievement
        self.assertEqual(await self.run_game(players.get_emeralds, winner), 170)
        self.assertEqual(await self.run_game(players.get_emeralds, loser), 50)
        self.assertEqual(await self.run_game(players.get_stat, winner, "duels_won"), 1)
        self.assertEqual(await self.run_game(players.get_stat, loser, "duels_lost"), 1)
        # The pot only moves between players: it doesn't count for the season.
        self.assertEqual((await self.run_game(seasons.overview, winner))["score"], 0)

    async def test_stake_rules(self):
        with self.assertRaises(GameError):
            await self.run_game(duel.fight, ALICE, BOB, 5)  # under the minimum
        with self.assertRaises(GameError):
            await self.run_game(duel.fight, ALICE, BOB, 101)
        with self.assertRaises(GameError):
            await self.run_game(duel.fight, ALICE, ALICE, 10)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 100)

    async def test_unequipping_mid_duel_does_not_avoid_wear(self):
        sword = await self.run_game(shop.create_gear, ALICE, "sword", "iron")
        await self.run_game(gear.equip, ALICE, sword)
        setup = await self.run_game(duel.start, ALICE, BOB, 10)
        await self.run_game(gear.unequip, ALICE, "sword")  # during the fight
        fight = setup["fight"]
        fight.auto_play(random.Random(3))
        await self.run_game(duel.finish, setup["duel_id"], fight)
        piece = (await self.run_game(shop.get_gear, ALICE))[0]
        self.assertGreater(fight.fighter(ALICE).attacks, 0)
        self.assertLess(piece["durability"], piece["max_durability"])

    async def test_gear_wears_during_fight(self):
        sword = await self.run_game(shop.create_gear, ALICE, "sword", "iron")
        helmet = await self.run_game(shop.create_gear, BOB, "helmet", "iron")
        await self.run_game(gear.equip, ALICE, sword)
        await self.run_game(gear.equip, BOB, helmet)
        await self.run_game(duel.fight, ALICE, BOB, 10)
        a = (await self.run_game(gear.get_equipped, ALICE))["sword"]
        b = (await self.run_game(gear.get_equipped, BOB))["helmet"]
        self.assertLess(a["durability"], a["max_durability"])
        self.assertLess(b["durability"], b["max_durability"])


if __name__ == "__main__":
    unittest.main()
