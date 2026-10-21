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
        self.assertEqual(len(data["locked"]), len(progress.ACHIEVEMENT_CODES) - 1)


class NewAchievementTests(GameTestCase):
    async def test_a_number_won_at_the_wheel(self):
        await self.run_game(players.bump_stat, ALICE, "roulette_numbers_won")
        self.assertIn("bullseye", await self.run_game(progress.unlocked_codes, ALICE))

    async def test_playing_during_a_gambling_frenzy(self):
        from game import live_events, luckyblock

        await self.run_game(players.give_emeralds, ALICE, 100)
        await self.run_game(luckyblock.open_block, ALICE, 10)
        self.assertNotIn("high_roller", await self.run_game(progress.unlocked_codes, ALICE))
        await self.run_game(live_events.start, "gambling_frenzy")
        await self.run_game(luckyblock.open_block, ALICE, 10)
        self.assertIn("high_roller", await self.run_game(progress.unlocked_codes, ALICE))

    async def test_challenges_count(self):
        await self.run_game(players.bump_stat, ALICE, "challenges_completed", 10)
        codes = await self.run_game(progress.unlocked_codes, ALICE)
        self.assertIn("challenger_10", codes)
        self.assertNotIn("challenger_50", codes)


class ChallengeTests(GameTestCase):
    def test_same_challenges_for_the_whole_week(self):
        a = progress.pick("week", "2026-W41")
        self.assertEqual(a, progress.pick("week", "2026-W41"))
        self.assertEqual(len(a), 3)
        self.assertEqual(len({c.code for c in a}), 3)

    def test_no_boss_challenge(self):
        weeks = [f"2026-W{w:02d}" for w in range(1, 53)]
        for week in weeks:  # gate bosses need a group and a dimension: not a challenge for everyone
            picks = progress.pick("week", week)
            self.assertEqual(len(picks), 3)
            self.assertNotIn("boss_damage", [c.code for c in picks])

    def test_nothing_needs_a_gate_boss(self):
        from game import biomes, settings

        self.assertNotIn("boss_damage", progress.CHALLENGE_CODES)  # bosses need the Nether: not for everyone
        self.assertEqual(biomes.BIOMES["mushroom"].challenge, "dummy")
        for b in biomes.BIOMES.values():
            self.assertIn(b.challenge, progress.CHALLENGE_CODES)
        old = {"challenges": {"goals": {"boss_damage": {"target": 100, "reward": 150}}}}
        self.assertEqual(settings.problems(old), [])  # an old config.json is fine

    def test_no_challenge_for_a_game_that_is_off(self):
        from game import settings

        settings.load({"games": {"quiz_every_minutes": 0, "roulette_enabled": False}})
        for day in range(1, 29):
            codes = [c.code for c in progress.pick("day", f"2026-02-{day:02d}")]
            self.assertEqual(len(codes), 3)
            self.assertFalse({"quiz", "wheel_spins"} & set(codes))

    async def test_challenge_completes_once(self):
        challenge = (await self.run_game(progress.current_challenges, "week"))[0]
        await self.run_game(players.bump_stat, ALICE, challenge.stat, challenge.target - 1)
        self.assertFalse(any(isinstance(n, ChallengeCompleted) and not n.daily for n in self.notices))
        await self.run_game(players.bump_stat, ALICE, challenge.stat, 5)
        await self.run_game(players.bump_stat, ALICE, challenge.stat, 5)
        done = [n for n in self.notices if isinstance(n, ChallengeCompleted) and not n.daily]
        self.assertEqual(len(done), 1)
        week = await self.run_game(progress.weekly_challenges, ALICE)
        entry = next(c for c in week if c["text"] == challenge.text)
        self.assertTrue(entry["completed"])
        self.assertEqual(entry["progress"], challenge.target)
        # Challenge rewards count for the season.
        self.assertGreaterEqual(await self.run_game(players.get_stat, ALICE, "emeralds_earned"), challenge.reward)

    async def test_progress_resets_next_week(self):
        challenge = (await self.run_game(progress.current_challenges, "week"))[0]
        await self.run_game(players.bump_stat, ALICE, challenge.stat, 1)
        self.advance(7 * DAY)
        week = await self.run_game(progress.weekly_challenges, ALICE)
        self.assertTrue(all(c["progress"] == 0 for c in week))

    async def test_daily_challenges(self):
        day = await self.run_game(progress.current_challenges, "day")
        self.assertEqual(len(day), 3)
        self.assertEqual(day, await self.run_game(progress.current_challenges, "day"))  # kept for the day
        c = day[0]
        await self.run_game(players.bump_stat, ALICE, c.stat, c.target)
        done = [n for n in self.notices if isinstance(n, ChallengeCompleted) and n.daily]
        self.assertEqual([(n.text, n.reward) for n in done], [(c.text, c.reward)])
        entry = next(e for e in await self.run_game(progress.daily_challenges, ALICE) if e["code"] == c.code)
        self.assertTrue(entry["completed"])
        self.advance(DAY)
        tomorrow = await self.run_game(progress.daily_challenges, ALICE)
        self.assertTrue(all(e["progress"] == 0 for e in tomorrow))

    async def test_never_the_same_as_the_day_or_week_before(self):
        before: dict[str, set] = {"day": set(), "week": set()}
        for n in range(35):
            for kind in ("day", "week"):
                codes = {c.code for c in await self.run_game(progress.current_challenges, kind)}
                if kind == "day" or n % 7 == 0:
                    self.assertFalse(codes & before[kind], (kind, n, codes, before[kind]))
                    before[kind] = codes
            self.advance(DAY)

    async def test_the_running_week_keeps_its_challenges(self):
        # The first week picked after the update is the one the old rules gave (old pool, same draw).
        import random

        week = self.week()
        old_pool = [c for c in progress.challenge_pool("week") if c.code in progress.LEGACY_WEEK_CODES]
        rng = random.Random(f"blocky-challenges-{week}")
        ok = [c for c in old_pool if progress.available(c)]
        picked = [c for c in rng.sample(old_pool, min(3, len(ok))) if progress.available(c)]
        spare = [c for c in rng.sample(old_pool, len(old_pool)) if progress.available(c) and c not in picked]
        self.assertEqual(await self.run_game(progress.current_challenges, "week"), (picked + spare)[:3])

    def week(self) -> str:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from game.db import week_id_of

        return week_id_of(datetime.fromtimestamp(self.now, ZoneInfo("Europe/Paris")))


if __name__ == "__main__":
    unittest.main()
