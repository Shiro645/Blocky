"""2.2.5: the economy rescaled to the ingot prices, and nothing a player can't do."""
from __future__ import annotations

import random
import unittest

from game import night, prestige, progress, quiz, settings, shop
from tests.helpers import GameTestCase

ALICE = 1


class NewDefaultsTests(unittest.TestCase):
    def setUp(self):
        settings.load()

    def test_the_new_numbers(self):
        s = settings.get()
        self.assertEqual(s["repair"]["anvil_iron"], 31)  # like Minecraft: 3 iron blocks + 4 ingots
        self.assertEqual(s["beacon"]["level_ingots"], [9, 27, 45, 81])
        self.assertEqual(s["pve"]["wave_rewards"], [25, 40, 60, 90, 135])
        self.assertEqual(s["challenges"]["goals"]["find_bedrock"]["target"], 1)
        self.assertNotIn("find_bedrock", s["challenges"]["daily_goals"])
        self.assertEqual(s["achievements"]["bedrock_100"]["goal"], 10)
        self.assertEqual(settings.problems({}), [])

    def test_a_full_repair_is_half_the_recipe(self):
        self.assertEqual({item: shop.full_repair_ingots(item) for item in ("shovel", "sword", "pickaxe", "chestplate",
                                                                            "shield")},
                         {"shovel": 1, "sword": 1, "pickaxe": 2, "chestplate": 4, "shield": 3})
        piece = {"item": "pickaxe", "max_durability": 1000, "durability": 0, "repairs": 0}
        self.assertEqual(shop.ingots_needed(piece), 2)
        self.assertEqual(shop.ingots_needed({**piece, "repairs": 2}), 3)  # +25% each repair: 2 × 1.5

    def test_old_settings_are_ignored_quietly(self):
        old = {"repair": {"durability_per_ingot": 0.25},
               "challenges": {"daily_goals": {"find_bedrock": {"target": 1, "reward": 40}}}}
        self.assertEqual(settings.problems(old), [])

    def test_night_monsters_are_fair_without_gear(self):
        from game import pve

        hp = float(settings.get()["pve"]["hp"])
        rng = random.Random(7)
        wins = sum(pve.fight_wave(rng, [pve.Hero(ALICE, 6.0, 1.0, 0.0, hp, hp)], 1, "normal",
                                  [night._monster("zombie")])["cleared"] for _ in range(400))
        self.assertGreater(wins / 400, 0.5)  # was about 10%

    def test_the_quiz_needs_its_channel(self):
        try:
            quiz.auto_channel = False
            self.assertFalse(progress.quiz_on())
            self.assertFalse(progress.achievement_open("quiz_10"))
            self.assertFalse(any(c.stat == "quiz_wins" for c in progress.pick("week", "2026-W10")))
        finally:
            quiz.auto_channel = True

    def test_switched_off_games_drop_out_of_prestige(self):
        self.assertTrue(progress.achievement_open("wheel_100"))
        settings.load({"games": {"roulette_enabled": False},
                       "live_events": {"random_kinds": {"gambling_frenzy": False}}})
        for code in ("wheel_100", "bullseye", "high_roller"):
            self.assertFalse(progress.achievement_open(code), code)
        self.assertTrue(progress.achievement_open("first_bedrock"))


class PrestigeTests(GameTestCase):
    async def test_prestige_counts_only_open_achievements(self):
        before = (await self.run_game(prestige.status, ALICE))["checks"]["achievements"][1]
        settings.load({"games": {"roulette_enabled": False}})
        after = (await self.run_game(prestige.status, ALICE))["checks"]["achievements"][1]
        self.assertEqual(before - after, 2)  # Spin Doctor and Bullseye
