"""PVE dungeon: the fight, groups, loot, death, potions and timeouts."""
from __future__ import annotations

import random

from game import potions, players, pve, settings
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB, CAROL = 1, 2, 3
MINUTE = 60


class FightTests(GameTestCase):
    def test_waves_and_difficulties(self):
        self.assertEqual(len(pve.WAVES), 5)
        self.assertEqual(list(pve.DIFFICULTIES), ["easy", "normal", "hard", "hardcore", "nightmare"])
        self.assertEqual(pve.wave_text(1), "3 🧟 Zombie")
        self.assertEqual(pve.wave_text(3, 2), "4 🧟 Zombie, 4 💀 Skeleton")
        self.assertAlmostEqual(pve.strength("normal", 3), 1.0 * 1.1 ** 2)
        diffs = settings.get()["pve"]["difficulties"]
        for a, b in zip(list(pve.DIFFICULTIES), list(pve.DIFFICULTIES)[1:]):
            with self.subTest(a=a, b=b):  # each difficulty costs more, hits harder, pays more
                self.assertLess(diffs[a]["entry"], diffs[b]["entry"])
                self.assertLess(diffs[a]["strength"], diffs[b]["strength"])
                self.assertLess(diffs[a]["reward"], diffs[b]["reward"])

    def test_good_gear_finishes_easy_and_health_is_kept(self):
        rng = random.Random(5)
        hero = pve.Hero(ALICE, 12, 1, 0.24, 20, 20)
        hp = []
        for wave in range(1, 6):
            self.assertTrue(pve.fight_wave(rng, [hero], wave, "easy")["cleared"])
            hp.append(hero.hp)
        self.assertEqual(hp, sorted(hp, reverse=True))  # never healed between waves
        self.assertLess(hp[-1], 20)

    def test_no_gear_dies_on_nightmare(self):
        rng = random.Random(5)
        hero = pve.Hero(ALICE, 6, 1, 0.0, 20, 20)
        results = [pve.fight_wave(rng, [hero], w, "nightmare") for w in range(1, 6) if hero.alive]
        self.assertFalse(hero.alive)
        self.assertIn(ALICE, results[-1]["deaths"])

    def test_a_group_faces_more_monsters_and_harming_hits_them_all(self):
        rng = random.Random(1)
        heroes = [pve.Hero(uid, 12, 1, 0.2, 20, 20) for uid in (ALICE, BOB)]
        heroes[0].harming = 100.0
        res = pve.fight_wave(rng, heroes, 1, "easy")
        self.assertEqual(res["monsters"], 6)
        self.assertTrue(res["cleared"])
        self.assertEqual(heroes[1].attacks, 0)  # Alice's potion killed everything
        self.assertEqual(heroes[0].harming, 0.0)  # a potion lasts one wave


class RunTests(GameTestCase):
    overrides = {"pve": {"difficulties": {"easy": {"strength": 0.3}}}}  # can't lose

    async def asyncSetUp(self):
        await super().asyncSetUp()
        for uid in (ALICE, BOB, CAROL):
            await self.run_game(players.give_emeralds, uid, 1000)

    async def emeralds(self, uid):
        return await self.run_game(players.get_emeralds, uid)

    async def test_a_solo_run_to_the_end(self):
        run = await self.run_game(pve.create, ALICE, "easy")
        self.assertEqual(await self.emeralds(ALICE), 970)
        res = await self.run_game(pve.start, run["run_id"], ALICE)
        self.assertEqual((res["wave"], res["result"]["cleared"], res["run"]["status"]), (1, True, "between"))
        with self.assertRaisesRegex(GameError, "already started"):
            await self.run_game(pve.next_wave, run["run_id"], ALICE, 0)  # an old button
        for wave in range(1, 5):
            res = await self.run_game(pve.next_wave, run["run_id"], ALICE, wave)
        self.assertTrue(res["cleared_all"])
        self.assertEqual(res["run"]["status"], "done")
        loot = sum(pve.wave_reward("easy", w) for w in range(1, 6))
        self.assertEqual(await self.emeralds(ALICE), 970 + round(loot * 1.5))
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "pve_clears_easy"), 1)
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "emeralds_earned"), round(loot * 1.5))
        with self.assertRaisesRegex(GameError, "enter the dungeon again"):
            await self.run_game(pve.create, ALICE, "easy")
        self.advance(60 * MINUTE)
        await self.run_game(pve.create, ALICE, "easy")

    async def test_a_group_lobby(self):
        run = await self.run_game(pve.create, ALICE, "normal")
        await self.run_game(pve.join, run["run_id"], BOB)
        with self.assertRaisesRegex(GameError, "already in this group"):
            await self.run_game(pve.join, run["run_id"], BOB)
        with self.assertRaisesRegex(GameError, "Only the leader"):
            await self.run_game(pve.start, run["run_id"], BOB)
        await self.run_game(pve.join, run["run_id"], CAROL)
        await self.run_game(pve.leave_lobby, run["run_id"], CAROL)
        self.assertEqual(await self.emeralds(CAROL), 1000)  # refunded
        await self.run_game(pve.leave_lobby, run["run_id"], ALICE)  # the leader cancels
        self.assertEqual((await self.emeralds(ALICE), await self.emeralds(BOB)), (1000, 1000))
        self.assertEqual((await self.run_game(pve.get, run["run_id"]))["status"], "cancelled")

    async def test_leave_with_the_loot_and_the_leader_passes(self):
        run = await self.run_game(pve.create, ALICE, "easy")
        await self.run_game(pve.join, run["run_id"], BOB)
        await self.run_game(pve.start, run["run_id"], ALICE)
        res = await self.run_game(pve.leave, run["run_id"], ALICE)
        self.assertEqual(res["paid"], pve.wave_reward("easy", 1))
        self.assertEqual(res["run"]["leader_id"], BOB)
        with self.assertRaisesRegex(GameError, "not fighting"):
            await self.run_game(pve.leave, run["run_id"], ALICE)
        res = await self.run_game(pve.next_wave, run["run_id"], BOB, 1)
        self.assertEqual(len(res["run"]["in"]), 1)

    async def test_death_loses_the_loot(self):
        run = await self.run_game(pve.create, ALICE, "easy")
        await self.run_game(pve.start, run["run_id"], ALICE)
        settings.load({"pve": {"difficulties": {"easy": {"strength": 50}}}})
        res = await self.run_game(pve.next_wave, run["run_id"], ALICE, 1)
        self.assertFalse(res["result"]["cleared"])
        member = res["run"]["members"][0]
        self.assertEqual((member["status"], member["paid"], res["run"]["status"]), ("dead", 0, "done"))
        self.assertEqual(await self.emeralds(ALICE), 970)
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "pve_deaths"), 1)

    async def test_potions_between_waves(self):
        await self.run_game(players.add_item, ALICE, "potion", "healing", 2)
        await self.run_game(players.add_item, ALICE, "potion", "strength", 5)
        run = await self.run_game(pve.create, ALICE, "easy")
        with self.assertRaisesRegex(GameError, "between two waves"):
            await self.run_game(pve.drink, run["run_id"], ALICE, "strength")
        await self.run_game(pve.start, run["run_id"], ALICE)
        res = await self.run_game(pve.drink, run["run_id"], ALICE, "strength")
        hero = res["run"]["in"][0]["hero"]
        self.assertEqual(hero.strength, potions.effect("strength", "strength_min_bonus"))
        settings.load({"pve": {"max_potions": 1, "difficulties": {"easy": {"strength": 0.3}}}})
        with self.assertRaisesRegex(GameError, "already drank 1"):
            await self.run_game(pve.drink, run["run_id"], ALICE, "strength")
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "potion", "strength"), 4)

    async def test_timeouts(self):
        lobby = await self.run_game(pve.create, BOB, "easy")
        run = await self.run_game(pve.create, ALICE, "easy")
        await self.run_game(pve.start, run["run_id"], ALICE)
        self.advance(5 * MINUTE)
        events = await self.run_game(pve.expire)
        self.assertEqual(sorted(e["type"] for e in events), ["cancelled", "timeout"])
        self.assertEqual(await self.emeralds(BOB), 1000)  # the group never started: refunded
        self.assertEqual(await self.emeralds(ALICE), 970 + pve.wave_reward("easy", 1))  # left with the loot
        self.assertEqual((await self.run_game(pve.get, lobby["run_id"]))["status"], "cancelled")
