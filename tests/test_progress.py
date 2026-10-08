from __future__ import annotations

import unittest

from game import gear, players, progress, shop
from game.catalog import ARMOR
from game.notices import AchievementUnlocked, ChallengeCompleted
from tests.helpers import DAY, GameTestCase

ALICE = 1


class AchievementTests(GameTestCase):
    async def test_stat_achievement_unlocks_once_and_pays(self):
        await self.run_game(players.bump_stat, ALICE, "bedrock_found", 1)
        await self.run_game(players.bump_stat, ALICE, "bedrock_found", 1)
        unlocked = [n for n in self.notices if isinstance(n, AchievementUnlocked)]
        self.assertEqual([n.code for n in unlocked], ["first_bedrock"])
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 25)
        # Rewards don't count as earned.
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "emeralds_earned"), 0)

    async def test_level_achievement(self):
        await self.run_game(players.set_level, ALICE, 25)
        codes = {n.code for n in self.notices if isinstance(n, AchievementUnlocked)}
        self.assertEqual(codes, {"level_10", "level_25"})

    async def test_full_armor_set(self):
        for slot in ARMOR:
            gid = await self.run_game(shop.create_gear, ALICE, slot, "diamond")
            await self.run_game(gear.equip, ALICE, gid)
        codes = {n.code for n in self.notices if isinstance(n, AchievementUnlocked)}
        self.assertEqual(codes, {"iron_set", "diamond_set"})

    async def test_overview(self):
        await self.run_game(players.bump_stat, ALICE, "items_crafted", 1)
        data = await self.run_game(progress.achievements_overview, ALICE)
        self.assertEqual([a.code for a, _ in data["unlocked"]], ["first_craft"])
        self.assertEqual(len(data["locked"]), len(progress.ACHIEVEMENTS) - 1)


class ChallengeTests(GameTestCase):
    def test_same_challenges_for_the_whole_week(self):
        a = progress.challenges_of_week("2026-W41")
        self.assertEqual(a, progress.challenges_of_week("2026-W41"))
        self.assertEqual(len(a), 3)
        self.assertEqual(len({c.code for c in a}), 3)

    async def test_challenge_completes_once(self):
        challenge = progress.challenges_of_week(self.week())[0]
        await self.run_game(players.bump_stat, ALICE, challenge.stat, challenge.target - 1)
        self.assertFalse(any(isinstance(n, ChallengeCompleted) for n in self.notices))
        await self.run_game(players.bump_stat, ALICE, challenge.stat, 5)
        await self.run_game(players.bump_stat, ALICE, challenge.stat, 5)
        done = [n for n in self.notices if isinstance(n, ChallengeCompleted)]
        self.assertEqual(len(done), 1)
        week = await self.run_game(progress.weekly_challenges, ALICE)
        entry = next(c for c in week if c["text"] == challenge.text)
        self.assertTrue(entry["completed"])
        self.assertEqual(entry["progress"], challenge.target)
        # Challenge rewards count for the season.
        self.assertGreaterEqual(await self.run_game(players.get_stat, ALICE, "emeralds_earned"), challenge.reward)

    async def test_progress_resets_next_week(self):
        challenge = progress.challenges_of_week(self.week())[0]
        await self.run_game(players.bump_stat, ALICE, challenge.stat, 1)
        self.advance(7 * DAY)
        week = await self.run_game(progress.weekly_challenges, ALICE)
        self.assertTrue(all(c["progress"] == 0 for c in week))

    def week(self) -> str:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from game.db import week_id_of

        return week_id_of(datetime.fromtimestamp(self.now, ZoneInfo("Europe/Paris")))


if __name__ == "__main__":
    unittest.main()
