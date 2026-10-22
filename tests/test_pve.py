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

    def test_monsters_follow_the_settings(self):
        settings.load({"pve": {"group_monsters": 0.5, "monsters": {"zombie": {"hp": 10.0}}}})
        self.assertEqual(pve.group_count(3, 1), 3)
        self.assertEqual(pve.group_count(3, 2), 5)  # +1.5 rounded
        self.assertEqual(pve.wave_text(1, 3), "6 🧟 Zombie")
        zombies = pve.spawn(1, "normal", 1)
        self.assertEqual([m.hp for m in zombies], [10.0] * 3)

    def test_nightmare_is_a_raid(self):
        settings.load()
        self.assertEqual(settings.get()["pve"]["max_players"], 5)
        nm = float(settings.get()["pve"]["difficulties"]["nightmare"]["group_monsters"])
        self.assertLess(nm, settings.get()["pve"]["group_monsters"])  # fewer monsters per extra player
        self.assertEqual(pve.group_count(4, 5, "nightmare"), 4 + round(4 * nm * 4))
        self.assertEqual(pve.group_count(4, 5, "hard"), 4 + 16)  # the others: a whole wave per player
        self.assertEqual(len(pve.spawn(1, "nightmare", 5)), pve.group_count(3, 5, "nightmare"))

    def test_two_harming_potions_count_each_kill_once(self):
        heroes = [pve.Hero(uid, 12, 1, 0.2, 20, 20) for uid in (ALICE, BOB)]
        heroes[0].harming = heroes[1].harming = 100.0
        res = pve.fight_wave(random.Random(1), heroes, 1, "easy")
        self.assertEqual(res["monsters"], 6)
        kills = "\n".join(res["log"] + res.get("summary", []))
        self.assertIn(f"<@{ALICE}>: 6 kills", kills)
        self.assertNotIn(f"<@{BOB}>: ", kills)  # Bob's potion hit nothing alive


class RunTests(GameTestCase):
    # Can't lose; no daily challenge paying for the waves on top of the loot.
    overrides = {"pve": {"difficulties": {"easy": {"strength": 0.3}}}, "challenges": {"per_day": 0}}

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
            await self.run_game(pve.ready, run["run_id"], ALICE, 0)  # an old button
        for wave in range(1, 5):
            res = (await self.run_game(pve.ready, run["run_id"], ALICE, wave))["last"]  # alone: it starts at once
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
        res = await self.run_game(pve.ready, run["run_id"], BOB, 1)
        self.assertEqual(len(res["run"]["in"]), 1)
        self.assertEqual(res["last"]["wave"], 2)

    async def test_death_loses_the_loot(self):
        run = await self.run_game(pve.create, ALICE, "easy")
        await self.run_game(pve.start, run["run_id"], ALICE)
        settings.load({"pve": {"difficulties": {"easy": {"strength": 50}}}})
        res = (await self.run_game(pve.ready, run["run_id"], ALICE, 1))["last"]
        self.assertFalse(res["result"]["cleared"])
        member = res["run"]["members"][0]
        self.assertEqual((member["status"], member["paid"], res["run"]["status"]), ("dead", 0, "done"))
        self.assertEqual(await self.emeralds(ALICE), 970)
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "pve_deaths"), 1)

    async def test_the_next_wave_waits_for_everyone(self):
        run = await self.run_game(pve.create, ALICE, "easy")
        await self.run_game(pve.join, run["run_id"], BOB)
        await self.run_game(pve.start, run["run_id"], ALICE)
        res = await self.run_game(pve.ready, run["run_id"], ALICE, 1)  # the leader can't go on alone
        self.assertIsNone(res["last"])
        self.assertEqual(res["run"]["wave"], 1)
        self.assertEqual([pve.is_ready(res["run"], m) for m in res["run"]["in"]], [True, False])
        with self.assertRaisesRegex(GameError, "already ready"):
            await self.run_game(pve.ready, run["run_id"], ALICE, 1)
        res = await self.run_game(pve.ready, run["run_id"], BOB, 1)  # everyone is ready: it starts
        self.assertEqual((res["last"]["wave"], res["run"]["wave"]), (2, 2))
        self.assertFalse(any(pve.is_ready(res["run"], m) for m in res["run"]["in"]))  # ready again for wave 3

    async def test_a_wave_not_cleared_asks_everyone_again(self):
        """A wave stopped by the round limit is played again: nobody may stay "already ready" (it blocked)."""
        from unittest import mock

        run = await self.run_game(pve.create, ALICE, "easy")
        await self.run_game(pve.join, run["run_id"], BOB)
        await self.run_game(pve.start, run["run_id"], ALICE)
        await self.run_game(pve.ready, run["run_id"], ALICE, 1)
        stuck = {"cleared": False, "log": [], "deaths": [], "monsters": 3, "damage": {}}
        with mock.patch.object(pve, "fight_wave", return_value=stuck):
            res = await self.run_game(pve.ready, run["run_id"], BOB, 1)
        self.assertEqual(res["run"]["wave"], 1)  # the same wave again
        self.assertFalse(any(pve.is_ready(res["run"], m) for m in res["run"]["in"]))
        res = await self.run_game(pve.ready, run["run_id"], ALICE, 1)  # no "already ready"
        self.assertIsNone(res["last"])

    async def test_leaving_lets_the_others_go_on(self):
        run = await self.run_game(pve.create, ALICE, "easy")
        await self.run_game(pve.join, run["run_id"], BOB)
        await self.run_game(pve.start, run["run_id"], ALICE)
        await self.run_game(pve.ready, run["run_id"], ALICE, 1)
        res = await self.run_game(pve.leave, run["run_id"], BOB)
        self.assertEqual(res["paid"], pve.wave_reward("easy", 1))
        self.assertEqual(res["last"]["wave"], 2)  # Alice only waited for Bob

    async def test_no_answer_in_time_leaves_and_the_others_go_on(self):
        run = await self.run_game(pve.create, ALICE, "easy")
        await self.run_game(pve.join, run["run_id"], BOB)
        await self.run_game(pve.start, run["run_id"], ALICE)
        await self.run_game(pve.ready, run["run_id"], BOB, 1)
        self.advance(5 * MINUTE)
        events = await self.run_game(pve.expire)
        self.assertEqual([e["type"] for e in events], ["continued"])
        self.assertEqual(events[0]["last"]["wave"], 2)
        members = {m["user_id"]: m for m in events[0]["run"]["members"]}
        self.assertEqual((members[ALICE]["status"], members[BOB]["status"]), ("left", "in"))
        self.assertEqual(events[0]["run"]["leader_id"], BOB)  # the leader left: Bob leads
        self.assertEqual(await self.emeralds(ALICE), 970 + pve.wave_reward("easy", 1))

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
        with self.assertRaisesRegex(GameError, "already drank a Strength potion"):  # it would be wasted
            await self.run_game(pve.drink, run["run_id"], ALICE, "strength")
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
