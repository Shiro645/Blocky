"""Training dummy: the damage tester and its leaderboard, and the training dummies."""
from __future__ import annotations

from game import dummy, gear, players, reset, settings, shop, species
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2


class TesterTests(GameTestCase):
    async def test_a_series_and_the_records(self):
        res = await self.run_game(dummy.hit_series, ALICE)
        self.assertEqual(len(res["hits"]), 10)
        low, high = res["attack"]
        for damage, crit in res["hits"]:
            self.assertTrue(low - 0.05 <= damage <= high * (2 if crit else 1) + 0.05)
        self.assertAlmostEqual(res["total"], sum(h for h, _ in res["hits"]), places=1)
        self.assertEqual((res["record"], res["rank"], res["players"]), (True, 1, 1))
        with self.assertRaisesRegex(GameError, "wobbling"):
            await self.run_game(dummy.hit_series, ALICE)
        self.advance(60)
        second = await self.run_game(dummy.hit_series, ALICE)
        self.assertEqual(second["best_total"], max(res["total"], second["total"]))

    async def test_gear_and_species_count_and_nothing_wears(self):
        gid = await self.run_game(shop.create_gear, BOB, "sword", "netherite")
        await self.run_game(gear.equip, BOB, gid)
        await self.run_game(species.choose, BOB, "dwarf")
        res = await self.run_game(dummy.hit_series, BOB)
        self.assertAlmostEqual(res["attack"][1], 14 * 1.05)
        sword = (await self.run_game(gear.get_equipped, BOB))["sword"]
        self.assertEqual(sword["durability"], sword["max_durability"])
        self.assertEqual(await self.run_game(players.get_stat, BOB, "emeralds_earned"), 0)

    async def test_leaderboard_and_reset(self):
        settings.load({"dummy": {"cooldown_seconds": 0}})
        for uid in (ALICE, BOB):
            await self.run_game(dummy.hit_series, uid)
        table = await self.run_game(dummy.ranking)
        self.assertEqual(sorted(r["user_id"] for r in table), [ALICE, BOB])
        self.assertGreaterEqual(table[0]["best_total"], table[1]["best_total"])
        await self.run_game(reset.apply, {"progress"}, ALICE)
        self.assertEqual([r["user_id"] for r in await self.run_game(dummy.ranking)], [BOB])


class TrainingDummyTests(GameTestCase):
    def test_dummies_follow_the_gear(self):
        none, iron, neth = (dummy.dummy_fighter(k) for k in ("none", "iron", "netherite"))
        self.assertEqual((none.attack, none.reduction, none.user_id), (6, 0.0, dummy.DUMMY_ID))
        self.assertEqual(iron.attack, 10)
        self.assertAlmostEqual(iron.reduction, 15 * 0.012)
        self.assertGreater(neth.reduction, iron.reduction)
        with self.assertRaises(GameError):
            dummy.dummy_fighter("wood")
