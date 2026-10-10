"""Mini-games: roulette, Blockdle and the quiz."""
from __future__ import annotations

import random
import unittest

from game import blockdle, players, quiz, roulette, settings
from game.blockdle_blocks import VERSIONS
from game.errors import GameError
from tests.helpers import DAY, GameTestCase

ALICE, BOB = 1, 2


class RouletteRules(unittest.TestCase):
    def setUp(self):
        settings.load()

    def tearDown(self):
        settings.load()

    def test_the_wheel(self):
        self.assertEqual(len(roulette.slots()), 38)
        self.assertEqual(sum(roulette.color(s) == "red" for s in roulette.slots()), 18)
        self.assertEqual(sum(roulette.color(s) == "green" for s in roulette.slots()), 2)
        settings.load({"games": {"roulette_zeros": 1}})
        self.assertEqual(roulette.slots()[:2], ["0", "1"])

    def test_every_bet_gives_back_the_same_on_average(self):
        for zeros, rate in ((2, 36 / 38), (1, 36 / 37)):
            settings.load({"games": {"roulette_zeros": zeros}})
            self.assertAlmostEqual(roulette.return_rate(), rate)
            for bet, (_, payout) in roulette.BETS.items():
                number = "17" if bet == "number" else None
                won = sum(roulette.wins(bet, number, s) for s in roulette.slots())
                with self.subTest(bet=bet, zeros=zeros):
                    self.assertAlmostEqual(payout * won / len(roulette.slots()), rate)

    def test_green_loses_everything_but_its_number(self):
        for bet in roulette.BETS:
            self.assertFalse(roulette.wins(bet, "1", "0"))
        self.assertTrue(roulette.wins("number", "00", "00"))


class RouletteGame(GameTestCase):
    async def test_spin_takes_the_bet_and_pays(self):
        await self.run_game(players.give_emeralds, ALICE, 1000)
        results = [await self.run_game(roulette.spin, ALICE, "red", 10) for _ in range(40)]
        paid = sum(r["payout"] for r in results)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 1000 - 400 + paid)
        self.assertTrue(all(r["payout"] in (0, 20) for r in results))
        self.assertTrue(all(r["won"] == (r["color"] == "red") for r in results))
        stats = await self.run_game(players.get_stats, ALICE)
        self.assertEqual((stats["roulette_spins"], stats["roulette_bet"]), (40, 400))
        self.assertEqual(stats.get("emeralds_earned", 0), 0)  # chance doesn't count for the seasons

    async def test_bets_are_checked(self):
        await self.run_game(players.give_emeralds, ALICE, 5000)
        with self.assertRaisesRegex(GameError, "Bets go"):
            await self.run_game(roulette.spin, ALICE, "red", 1001)
        with self.assertRaisesRegex(GameError, "Pick the number"):
            await self.run_game(roulette.spin, ALICE, "number", 10, "37")
        with self.assertRaisesRegex(GameError, "Not enough"):
            await self.run_game(roulette.spin, BOB, "red", 10)
        res = await self.run_game(roulette.spin, ALICE, "number", 10, "00")
        self.assertEqual(res["payout"], 360 if res["slot"] == "00" else 0)


class BlockdleRules(unittest.TestCase):
    def test_the_blocks(self):
        self.assertGreaterEqual(len(blockdle.BLOCKS), 150)
        self.assertEqual(len(blockdle.BY_ID), len(blockdle.BLOCKS))
        self.assertEqual(len({b.name for b in blockdle.BLOCKS}), len(blockdle.BLOCKS))
        for b in blockdle.BLOCKS:
            with self.subTest(block=b.id):
                self.assertIn(b.version, VERSIONS)
                self.assertIn(b.tool, ("Pickaxe", "Axe", "Shovel", "Hoe", "Shears", "Sword", "Any", "None"))
                self.assertLessEqual(len(b.name), 100)
        stone, diamond = blockdle.find("stone"), blockdle.find("block of diamond")
        self.assertEqual((stone.hardness, stone.resistance, stone.version), (1.5, 6.0, "Classic"))
        self.assertTrue(diamond.craftable)

    def test_compare(self):
        stone, bedrock = blockdle.find("Stone"), blockdle.find("Bedrock")
        cells = blockdle.compare(stone, bedrock)
        self.assertEqual(cells["hardness"], "higher")  # unbreakable is the hardest
        self.assertEqual(cells["version"], "yes")
        self.assertEqual(set(blockdle.compare(stone, stone).values()), {"yes"})
        crafter = blockdle.find("crafter")
        self.assertEqual(blockdle.compare(crafter, stone)["version"], "lower")

    def test_search(self):
        names = [b.name for b in blockdle.search("block of")]
        self.assertIn("Block of Diamond", names)
        self.assertEqual(blockdle.search("dia")[0].name, "Diamond Ore")  # names starting with the text first
        with self.assertRaises(GameError):
            blockdle.find("unobtainium")


class BlockdleGame(GameTestCase):
    async def secret(self):
        return await self.run_game(blockdle.block_of_day)

    async def test_the_block_of_the_day_stays_the_same(self):
        first = await self.secret()
        self.assertEqual(await self.secret(), first)
        self.advance(DAY)
        days = {first.id}
        for _ in range(20):
            days.add((await self.secret()).id)
            self.advance(DAY)
        self.assertEqual(len(days), 21)  # no block twice in a row of days

    async def test_guessing(self):
        secret = await self.secret()
        wrong = next(b for b in blockdle.BLOCKS if b.id != secret.id)
        res = await self.run_game(blockdle.guess, ALICE, wrong.name)
        self.assertFalse(res["found"])
        self.assertEqual(res["guesses"][0][0], wrong)
        with self.assertRaisesRegex(GameError, "already tried"):
            await self.run_game(blockdle.guess, ALICE, wrong.id)
        res = await self.run_game(blockdle.guess, ALICE, secret.id)
        self.assertTrue(res["found"])
        self.assertEqual((res["tries"], res["reward"]), (2, 250))
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 250)
        with self.assertRaisesRegex(GameError, "already found"):
            await self.run_game(blockdle.guess, ALICE, wrong.id)
        await self.run_game(blockdle.guess, BOB, secret.id)
        winners = await self.run_game(blockdle.winners)
        self.assertEqual([w["user_id"] for w in winners], [BOB, ALICE])  # fewest guesses first

    async def test_rewards_follow_the_settings(self):
        settings.load({"games": {"blockdle_rewards": [9, 8, 7, 6, 5, 4, 3, 2, 1, 1]}})
        self.assertEqual([blockdle.reward_for(n) for n in (1, 2, 10, 50)], [9, 8, 1, 1])

    async def test_a_new_day_starts_over(self):
        secret = await self.secret()
        await self.run_game(blockdle.guess, ALICE, secret.id)
        self.advance(DAY)
        state = await self.run_game(blockdle.state, ALICE)
        self.assertEqual((state["guesses"], state["found"]), ([], False))
        self.assertEqual(await self.run_game(blockdle.yesterday), secret)


class QuizTests(GameTestCase):
    def test_questions(self):
        self.assertGreaterEqual(len(quiz.QUESTIONS), 80)
        self.assertEqual(len({q for q, _, _ in quiz.QUESTIONS}), len(quiz.QUESTIONS))
        for question, right, wrong in quiz.QUESTIONS:
            with self.subTest(question=question):
                self.assertEqual(len({right, *wrong}), 4)
                self.assertLessEqual(max(len(a) for a in (right, *wrong)), 76)  # a button label: "A. " + the answer

    def test_answers_are_shuffled_and_recent_questions_skipped(self):
        rng = random.Random(5)
        positions = set()
        for _ in range(30):
            options, right = quiz.answers(rng, 0)
            self.assertEqual(options[right], quiz.QUESTIONS[0][1])
            positions.add(right)
        self.assertGreater(len(positions), 1)
        recent = list(range(len(quiz.QUESTIONS) - 1))
        self.assertEqual(quiz.pick(rng, recent), len(quiz.QUESTIONS) - 1)

    async def test_reward(self):
        res = await self.run_game(quiz.reward, ALICE)
        self.assertEqual(res, {"emeralds": 50, "xp": 20})
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "quiz_wins"), 1)


if __name__ == "__main__":
    unittest.main()
