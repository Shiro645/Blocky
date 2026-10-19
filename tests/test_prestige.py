"""Prestige (2.0.7): the conditions, what starts over, the bonuses and the cosmetics."""
from __future__ import annotations

from game import beacon, dimensions, players, prestige, profiles, progress, reset, settings
from game.errors import GameError
from game.notices import PrestigeReached
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2


class PrestigeTestCase(GameTestCase):
    async def make_ready(self, uid: int = ALICE, level: int = 50) -> None:
        """Every condition: the level, every achievement, every dimension and the Beacon lit."""
        def run(ctx):
            players.set_level(ctx, uid, level)
            for a in progress.achievements():
                ctx.execute("INSERT OR IGNORE INTO achievements(user_id, code, unlocked_at) VALUES(?, ?, ?);",
                            (uid, a.code, int(ctx.now)))
            dimensions.set_highest(ctx, uid, "shimmer")
            beacon.staff_set(ctx, True)

        await self.run_game(run)


class ConditionTests(PrestigeTestCase):
    async def test_every_condition_is_needed(self):
        st = await self.run_game(prestige.status, ALICE)
        self.assertEqual((st["next"], st["ready"]), (1, False))
        self.assertEqual(st["checks"]["level"], (1, 50))
        with self.assertRaisesRegex(GameError, "condition"):
            await self.run_game(prestige.ascend, ALICE)
        await self.make_ready()
        self.assertTrue((await self.run_game(prestige.status, ALICE))["ready"])
        await self.run_game(lambda ctx: beacon.staff_set(ctx, False))
        self.assertFalse((await self.run_game(prestige.status, ALICE))["ready"])  # the Beacon went out

    async def test_each_prestige_needs_ten_more_levels_up_to_ten(self):
        self.assertEqual([prestige.level_needed(n) for n in (1, 2, 3, 10)], [50, 60, 70, 140])
        await self.run_game(prestige.set_prestige, ALICE, 1)
        await self.make_ready(level=59)
        self.assertEqual((await self.run_game(prestige.status, ALICE))["checks"]["level"], (59, 60))
        await self.run_game(prestige.set_prestige, ALICE, 10)
        st = await self.run_game(prestige.status, ALICE)
        self.assertIsNone(st["next"])
        with self.assertRaisesRegex(GameError, "highest"):
            await self.run_game(prestige.ascend, ALICE)


class AscendTests(PrestigeTestCase):
    async def test_everything_but_the_level_starts_over(self):
        await self.make_ready()
        await self.run_game(players.give_emeralds, ALICE, 5000)
        await self.run_game(players.add_blocks, ALICE, "cobblestone", 100)
        await self.run_game(players.bump_stat, ALICE, "blocks_mined", 100)
        res = await self.run_game(prestige.ascend, ALICE)
        self.assertEqual(res["prestige"], 1)
        user = await self.run_game(players.get_user, ALICE)
        self.assertEqual((user["level"], user["prestige"], user["emeralds"], user["dimension_level"]), (50, 1, 0, 0))
        self.assertFalse(any((await self.run_game(players.get_blocks, ALICE)).values()))
        self.assertEqual(await self.run_game(progress.unlocked_codes, ALICE), {})
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "blocks_mined"), 0)
        self.assertIn(PrestigeReached(ALICE, 1), self.notices)

    async def test_the_reset_follows_the_settings(self):
        settings.load({"prestige": {"reset": {"wealth": False, "gear": True, "achievements": False,
                                              "dimensions": False}}})
        await self.make_ready()
        await self.run_game(players.give_emeralds, ALICE, 5000)
        before = await self.run_game(players.get_emeralds, ALICE)
        await self.run_game(prestige.ascend, ALICE)
        user = await self.run_game(players.get_user, ALICE)
        self.assertEqual((user["emeralds"], user["dimension_level"]), (before, 4))
        self.assertEqual(len(await self.run_game(progress.unlocked_codes, ALICE)), len(progress.achievements()))

    async def test_bonus_stars_and_cosmetics(self):
        await self.run_game(prestige.set_prestige, ALICE, 2)
        user = await self.run_game(players.get_user, ALICE)
        self.assertAlmostEqual(prestige.bonus(user), 0.10)
        self.assertEqual(await self.run_game(players.prestige_marks, [ALICE, BOB]), {ALICE: "⭐⭐"})
        self.assertEqual(prestige.stars(5), "⭐×5")
        titles = dict(await self.run_game(profiles.titles_of, ALICE))
        self.assertEqual((await self.run_game(profiles.frames_of, ALICE))["prestige"], "owned")
        self.assertIn("reborn", titles)
        self.assertNotIn("mythic", titles)

    async def test_sell_gets_the_bonus(self):
        await self.run_game(players.add_blocks, ALICE, "cobblestone", 1000)
        await self.run_game(prestige.set_prestige, ALICE, 3)
        res = await self.run_game(players.sell_blocks, ALICE)
        self.assertEqual(res["bonus"], 150)

    async def test_reset_of_the_levels_resets_the_prestige(self):
        await self.run_game(prestige.set_prestige, ALICE, 4)
        await self.run_game(reset.apply, {"levels"}, ALICE)
        self.assertEqual((await self.run_game(players.get_user, ALICE))["prestige"], 0)
        self.assertEqual(await self.run_game(prestige.holders), [])
