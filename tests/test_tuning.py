"""Values that used to be written in the code and now come from the settings."""
from __future__ import annotations

import random
import unittest

from game import mining, players, progress, settings
from game.notices import AchievementUnlocked, ChallengeCompleted
from tests.helpers import GameTestCase

ALICE = 1
NONE = {"cobblestone": 0, "gravel": 0, "deepslate": 0, "obsidian": 0, "bedrock": 0}


class TuningTests(unittest.TestCase):
    def setUp(self):
        settings.load()

    def tearDown(self):
        settings.load()

    def test_xp_curve(self):
        self.assertEqual([players.xp_required_for_level(n) for n in (1, 2, 10)], [100, 125, 325])
        settings.load({"levels": {"xp_first_level": 50, "xp_increase_per_level": 0}})
        self.assertEqual([players.xp_required_for_level(n) for n in (1, 2, 10)], [50, 50, 50])

    def test_mining_odds(self):
        settings.load({"mining": {"odds_1_block": {**NONE, "bedrock": 1}, "odds_2_3_blocks": {**NONE, "obsidian": 5}}})
        rng = random.Random(3)
        for _ in range(300):
            block, amount = mining.roll_blocks(rng, 0, 0)
            if amount == 1:
                self.assertEqual(block, "bedrock")
            elif amount <= 3:
                self.assertEqual(block, "obsidian")

    def test_talent_bonuses_follow_the_settings(self):
        self.assertEqual(mining.pile_weights(5, miner=8, lucky=0)["gravel"], 30 + 40)  # capped at +40
        settings.load({"talents": {"miner_gravel_4_5": 1, "lucky_rare_weight": 10}})
        self.assertEqual(mining.pile_weights(5, miner=8, lucky=0)["gravel"], 30 + 8)
        self.assertEqual(mining.pile_weights(1, miner=0, lucky=2)["bedrock"], 1 + 20)

    def test_challenge_texts_follow_the_targets(self):
        texts = {c.code: c.text for c in progress.challenge_pool()}
        self.assertEqual(texts["mine_blocks"], "Mine 500 blocks")
        self.assertEqual(texts["sell_blocks"], "Earn 1,000 emeralds by selling blocks")
        settings.load({"challenges": {"goals": {"win_duels": {"target": 1, "reward": 10}}}})
        duel = next(c for c in progress.challenge_pool() if c.code == "win_duels")
        self.assertEqual((duel.text, duel.target, duel.reward), ("Win 1 duel", 1, 10))

    def test_achievement_texts_follow_the_goals(self):
        settings.load({"achievements": {"miner_1k": {"goal": 2500, "reward": 7}}})
        miner = next(a for a in progress.achievements() if a.code == "miner_1k")
        self.assertEqual((miner.description, miner.reward), ("Mine 2,500 blocks", 7))
        self.assertEqual(len(progress.achievements()), len(settings.DEFAULTS["achievements"]))

    def test_new_goals_are_checked(self):
        problems = settings.problems({"achievements": {"gladiator": {"goal": 0}}, "challenges": {"goals": {"trades": {"target": 0}}}})
        self.assertEqual(len(problems), 2)


class TuningGameTests(GameTestCase):
    async def test_achievement_goal_and_reward_from_settings(self):
        settings.load({"achievements": {"gladiator": {"goal": 2, "reward": 77}}})
        await self.run_game(players.bump_stat, ALICE, "duels_won", 2)
        codes = {n.code: n.reward for n in self.notices if isinstance(n, AchievementUnlocked)}
        self.assertEqual(codes.get("gladiator"), 77)

    async def test_challenge_target_from_settings(self):
        settings.load({"challenges": {"per_week": 9, "goals": {"claim_drops": {"target": 1, "reward": 42}}}})
        await self.run_game(players.bump_stat, ALICE, "drops_claimed", 1)
        done = [n for n in self.notices if isinstance(n, ChallengeCompleted)]
        self.assertTrue(any(n.reward == 42 and n.text == "Claim 1 drop" for n in done), done)


if __name__ == "__main__":
    unittest.main()
