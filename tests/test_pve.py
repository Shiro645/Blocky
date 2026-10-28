"""PVE dungeon: the fight, groups, loot, death, potions and timeouts."""
from __future__ import annotations

import random

from game import potions, players, pve, settings
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB, CAROL = 1, 2, 3
MINUTE = 60


class FightTests(GameTestCase):
    legacy_economy = False  # 2.3: a fixed number of monsters per difficulty

    @staticmethod
    def heroes(n: int, attack: float = 6, reduction: float = 0.0) -> list[pve.Hero]:
        low = float(settings.get()["duel"]["min_damage"])
        return [pve.Hero(uid, attack, low, reduction, 20, 20) for uid in range(1, n + 1)]

    def clears(self, n: int, difficulty: str, runs: int = 60, **kit) -> float:
        rng, won = random.Random(3), 0
        for _ in range(runs):
            heroes = self.heroes(n, **kit)
            won += all(pve.fight_wave(rng, heroes, w, difficulty)["cleared"] for w in range(1, 6))
        return won / runs

    def test_waves_and_difficulties(self):
        self.assertEqual(len(pve.WAVES), 5)
        self.assertEqual(list(pve.DIFFICULTIES), ["easy", "normal", "hard", "hardcore", "nightmare"])
        self.assertEqual(pve.wave_text(1, "easy"), "9 🧟 Zombie")
        self.assertEqual(pve.wave_text(3, "nightmare"), "9 🧟 Zombie, 9 💀 Skeleton")
        self.assertAlmostEqual(pve.strength("normal", 3), 0.99 * 1.1 ** 2)
        diffs = settings.get()["pve"]["difficulties"]
        for a, b in zip(list(pve.DIFFICULTIES), list(pve.DIFFICULTIES)[1:]):
            with self.subTest(a=a, b=b):  # each difficulty costs more, hits harder, pays more
                self.assertLess(diffs[a]["entry"], diffs[b]["entry"])
                self.assertLess(diffs[a]["strength"], diffs[b]["strength"])
                self.assertLessEqual(diffs[a]["monsters"], diffs[b]["monsters"])
                self.assertLess(diffs[a]["reward"], diffs[b]["reward"])

    def test_the_monsters_dont_change_with_the_group(self):
        alone = pve.fight_wave(random.Random(1), self.heroes(1), 1, "easy")
        group = pve.fight_wave(random.Random(1), self.heroes(5), 1, "easy")
        self.assertEqual((alone["monsters"], group["monsters"]), (9, 9))

    def test_made_for_a_group_never_alone(self):
        self.assertEqual(self.clears(1, "easy", attack=17.5, reduction=0.39), 0)  # alone, even in netherite
        self.assertEqual(self.clears(2, "easy"), 0)
        self.assertGreater(self.clears(3, "easy"), 0.4)  # Easy: 3 players without gear
        self.assertGreater(self.clears(3, "hard", attack=12, reduction=0.24), 0.3)  # Hard: 3 in diamond
        self.assertLess(self.clears(3, "hard", attack=10, reduction=0.18), 0.2)  # ...not in iron

    def test_health_is_kept_between_waves(self):
        rng = random.Random(5)
        heroes = self.heroes(5, attack=10, reduction=0.18)
        hp = []
        for wave in range(1, 6):
            self.assertTrue(pve.fight_wave(rng, heroes, wave, "easy")["cleared"])
            hp.append(sum(h.hp for h in heroes))
        self.assertEqual(hp, sorted(hp, reverse=True))  # never healed between waves
        self.assertLess(hp[-1], 100)

    def test_no_gear_dies_on_nightmare(self):
        rng = random.Random(5)
        [hero] = self.heroes(1)
        results = [pve.fight_wave(rng, [hero], w, "nightmare") for w in range(1, 6) if hero.alive]
        self.assertFalse(hero.alive)
        self.assertIn(1, results[-1]["deaths"])

    def test_harming_hits_three_monsters(self):
        heroes = self.heroes(3, attack=12)
        heroes[0].harming = 100.0
        res = pve.fight_wave(random.Random(1), heroes, 1, "easy")
        self.assertIn(f"☠️ <@{ALICE}> throws a Harming potion: -100 HP to 3 monsters", res["log"])
        self.assertEqual(heroes[0].harming, 0.0)  # a potion lasts one wave

    def test_harming_can_hit_them_all_and_counts_each_kill_once(self):
        settings.load({"pve": {"harming_targets": 0}})
        heroes = self.heroes(2, attack=12)
        heroes[0].harming = heroes[1].harming = 100.0
        res = pve.fight_wave(random.Random(1), heroes, 1, "easy")
        self.assertTrue(res["cleared"])
        self.assertEqual(heroes[1].attacks, 0)  # Alice's potion killed everything
        kills = "\n".join(res["log"])
        self.assertIn(f"<@{ALICE}>: 9 kills", kills)
        self.assertNotIn(f"<@{BOB}>: ", kills)  # Bob's potion hit nothing alive

    def test_monsters_follow_the_settings(self):
        settings.load({"pve": {"monsters": {"zombie": {"hp": 10.0}}, "difficulties": {"normal": {"monsters": 2.0}}}})
        self.assertEqual(pve.wave_text(1, "normal"), "6 🧟 Zombie")
        zombies = pve.spawn(1, "normal")
        self.assertEqual(len(zombies), 6)
        self.assertAlmostEqual(zombies[0].hp, 10.0 * 0.99)


class SharedLootTests(GameTestCase):
    legacy_economy = False
    overrides = {"pve": {"difficulties": {"easy": {"strength": 0.1}}}, "challenges": {"per_day": 0}}

    async def wave_one(self, *uids: int) -> dict:
        for uid in uids:
            await self.run_game(players.give_emeralds, uid, 1000)
        run = await self.run_game(pve.create, uids[0], "easy")
        for uid in uids[1:]:
            await self.run_game(pve.join, run["run_id"], uid)
        return await self.run_game(pve.start, run["run_id"], uids[0])

    async def test_the_loot_is_shared_by_the_survivors(self):
        self.assertEqual(pve.wave_pot("easy", 1), pve.wave_reward("easy", 1) * 3)
        res = await self.wave_one(ALICE, BOB, CAROL)  # the group Easy is made for: the full reward each
        self.assertEqual(res["reward"], pve.wave_reward("easy", 1))
        self.assertEqual([m["loot"] for m in res["run"]["in"]], [pve.wave_reward("easy", 1)] * 3)

    async def test_a_bigger_group_earns_less_each(self):
        res = await self.wave_one(ALICE, BOB, CAROL, 4, 5)
        self.assertEqual(res["reward"], round(pve.wave_pot("easy", 1) / 5))


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
        self.assertEqual(res["paid"], round(pve.wave_pot("easy", 1) / 2))  # shared by the two
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
        self.assertEqual(res["paid"], round(pve.wave_pot("easy", 1) / 2))
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
        self.assertEqual(await self.emeralds(ALICE), 970 + round(pve.wave_pot("easy", 1) / 2))

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
        self.assertEqual(await self.emeralds(ALICE), 970 + pve.wave_pot("easy", 1))  # left with the loot
        self.assertEqual((await self.run_game(pve.get, lobby["run_id"]))["status"], "cancelled")


class LapisTests(GameTestCase):
    legacy_economy = False
    overrides = {"pve": {"difficulties": {"easy": {"strength": 0.1, "lapis_chance": 1.0, "lapis": [2, 2]}}},
                 "challenges": {"per_day": 0}}

    async def test_survivors_find_lapis_and_keep_it(self):
        for uid in (ALICE, BOB):
            await self.run_game(players.give_emeralds, uid, 1000)
        run = await self.run_game(pve.create, ALICE, "easy")
        await self.run_game(pve.join, run["run_id"], BOB)
        res = await self.run_game(pve.start, run["run_id"], ALICE)
        self.assertEqual(res["lapis"], {ALICE: 2, BOB: 2})
        for uid in (ALICE, BOB):
            self.assertEqual(await self.run_game(players.item_amount, uid, "lapis", "none"), 2)
            self.assertEqual((await self.run_game(players.get_stats, uid)).get("lapis_found"), 2)

    async def test_no_chance_no_lapis(self):
        settings.load({"pve": {"difficulties": {"easy": {"strength": 0.1, "lapis_chance": 0.0}}}})
        await self.run_game(players.give_emeralds, ALICE, 1000)
        run = await self.run_game(pve.create, ALICE, "easy")
        res = await self.run_game(pve.start, run["run_id"], ALICE)
        self.assertEqual(res["lapis"], {})

    def test_harder_gives_more_lapis(self):
        diffs = settings.DEFAULTS["pve"]["difficulties"]
        mean = [diffs[k]["lapis_chance"] * sum(diffs[k]["lapis"]) / 2 for k in pve.DIFFICULTIES]
        self.assertEqual(mean, sorted(mean))


class ExpireRunTests(GameTestCase):
    overrides = {"pve": {"difficulties": {"easy": {"strength": 0.3}}}, "challenges": {"per_day": 0}}

    async def test_a_click_before_the_loop_wins(self):
        await self.run_game(players.give_emeralds, ALICE, 1000)
        run = await self.run_game(pve.create, ALICE, "easy")
        await self.run_game(pve.start, run["run_id"], ALICE)
        self.advance(5 * MINUTE)
        self.assertEqual(await self.run_game(pve.expired), [run["run_id"]])
        await self.run_game(pve.leave, run["run_id"], ALICE)  # clicked just before the loop got the run
        self.assertIsNone(await self.run_game(pve.expire_run, run["run_id"]))
