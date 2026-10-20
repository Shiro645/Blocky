"""Gang wars (2.0.4): team chests, the weekly war's points and pot, and raids."""
from __future__ import annotations

import random

from game import duel, players, robbery, settings, teams, war
from game.errors import GameError
from tests.helpers import DAY, GameTestCase

A1, A2, A3, B1, B2, C1, C2 = 1, 2, 3, 11, 12, 21, 22
MINUTE = 60


class WarTestCase(GameTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for uid in (A1, A2, A3, B1, B2, C1, C2):
            await self.run_game(players.give_emeralds, uid, 10_000)
        self.ta = await self.team(A1, "Alpha", "AAA", A2, A3)
        self.tb = await self.team(B1, "Bravo", "BBB", B2)

    async def team(self, leader: int, name: str, tag: str, *others: int) -> int:
        t = await self.run_game(teams.create, leader, name, tag)
        for uid in others:
            await self.run_game(teams.invite, leader, uid)
            await self.run_game(teams.accept, uid, t["team_id"])
        return t["team_id"]


class ChestTests(WarTestCase):
    async def test_deposit_and_leader_withdraw(self):
        res = await self.run_game(war.deposit, A2, 1000)
        self.assertEqual(res["chest"], 1000)
        with self.assertRaisesRegex(GameError, "leader"):
            await self.run_game(war.withdraw, A2, 100)
        await self.run_game(war.withdraw, A1, 400)
        self.assertEqual(await self.run_game(war.chest, self.ta), 600)
        with self.assertRaisesRegex(GameError, "only holds"):
            await self.run_game(war.withdraw, A1, 601)

    async def test_disbanding_gives_the_chest_to_the_leader(self):
        await self.run_game(war.deposit, B2, 500)
        before = await self.run_game(players.get_emeralds, B1)
        await self.run_game(teams.disband, B1)
        self.assertEqual(await self.run_game(players.get_emeralds, B1), before + 500)


class PointTests(WarTestCase):
    async def test_duels_between_enemies_with_a_daily_cap(self):
        for _ in range(4):
            self.assertIn(await self.run_game(war.on_duel, A1, B1), (0, 1))
        st = await self.run_game(war.standings)
        self.assertEqual({t["tag"]: t["points"] for t in st}, {"AAA": 3, "BBB": 0})
        self.assertEqual(await self.run_game(war.on_duel, A1, A2), 0)  # teammates
        self.assertEqual(await self.run_game(war.on_duel, A1, C1), 0)  # not in a team

    async def test_a_real_duel_scores(self):
        rng = random.Random(1)

        def play(ctx):
            res = duel.start(ctx, A1, B1, 10, rng)
            res["fight"].auto_play(rng)
            return duel.finish(ctx, res["duel_id"], res["fight"])

        out = await self.run_game(play)
        self.assertEqual(out["war_points"], 1)
        st = {t["tag"]: t["points"] for t in await self.run_game(war.standings)}
        self.assertEqual(st["AAA" if out["winner"] == A1 else "BBB"], 1)

    async def test_robberies_between_enemies(self):
        await self.run_game(players.set_level, B1, 10)
        self.now = self.now  # robberies only start in the daytime (tests start at noon)
        rob = await self.run_game(robbery.start, A1, B1, "discreet")
        self.advance(61 * MINUTE)
        done = await self.run_game(robbery.finish_due)
        self.assertEqual(done[0]["war_points"], 2)
        await self.run_game(players.set_level, A2, 10)
        rob = await self.run_game(robbery.start, B2, A2, "discreet")
        res = await self.run_game(robbery.stop, rob["rob_id"], A2)
        self.assertEqual(res["war_points"], 1)
        st = {t["tag"]: t["points"] for t in await self.run_game(war.standings)}
        self.assertEqual(st, {"AAA": 3, "BBB": 0})

    async def test_the_week_pays_the_podium(self):
        await self.run_game(war.deposit, A1, 2000)
        await self.run_game(war.deposit, B1, 1000)
        res = await self.run_game(war.weekly)  # the first run: this week's levy
        self.assertEqual(res["pot"], 100 + 50)
        await self.run_game(war.on_duel, B1, A1)
        self.advance(7 * DAY)
        res = await self.run_game(war.weekly)
        self.assertEqual([(t["tag"], t["paid"]) for t in res["podium"]], [("BBB", int(150 * 0.9 * 0.5))])
        self.assertEqual(await self.run_game(players.get_stat, B2, "wars_won"), 1)
        self.assertIsNone(await self.run_game(war.weekly))  # once a week


class RaidTests(WarTestCase):
    async def test_a_raid_nobody_defends(self):
        await self.run_game(war.deposit, B1, 1000)
        raid = await self.run_game(war.start_raid, A1, "BBB")
        with self.assertRaisesRegex(GameError, "at least 2"):
            await self.run_game(war.launch_raid, raid["raid_id"], A1)
        with self.assertRaisesRegex(GameError, "raiding team"):
            await self.run_game(war.join_raid, raid["raid_id"], B2)
        await self.run_game(war.join_raid, raid["raid_id"], A2)
        raid = await self.run_game(war.launch_raid, raid["raid_id"], A1)
        self.assertEqual(raid["status"], "defending")
        self.advance(31 * MINUTE)
        raid = (await self.run_game(war.due_raids))[0]
        self.assertEqual((raid["status"], raid["stolen"]), ("won", 300))
        self.assertEqual(await self.run_game(war.chest, self.ta), 300)
        st = {t["tag"]: t["points"] for t in await self.run_game(war.standings)}
        self.assertEqual(st["AAA"], 5)
        self.advance(3 * 3600)
        await self.run_game(lambda ctx: ctx.execute("DELETE FROM raids WHERE status='cancelled';"))
        settings.load({"war": {"raids_per_day": 5}})
        with self.assertRaisesRegex(GameError, "safe until"):
            await self.run_game(war.start_raid, A3, "BBB")

    async def test_defenders_fight(self):
        raid = await self.run_game(war.start_raid, B1, "AAA")
        await self.run_game(war.join_raid, raid["raid_id"], B2)
        await self.run_game(war.launch_raid, raid["raid_id"], B1)
        for uid in (A1, A2, A3):
            await self.run_game(war.join_raid, raid["raid_id"], uid)
        raid = await self.run_game(war.resolve_raid, raid["raid_id"])
        self.assertEqual(raid["status"], "fighting")
        fight = war.fight_of(raid)
        self.assertEqual([f.side for f in fight.fighters], ["attack", "defend", "attack", "defend", "defend"])
        current = fight.current.user_id
        other = next(f.user_id for f in fight.fighters if f.user_id != current)
        with self.assertRaisesRegex(GameError, "turn"):
            await self.run_game(war.raid_attack, raid["raid_id"], other)
        raid = await self.run_game(war.raid_attack, raid["raid_id"], current)
        self.assertNotEqual(war.fight_of(raid).current.user_id, current)
        raid = await self.run_game(war.play_out, raid["raid_id"])
        self.assertIn(raid["status"], ("won", "lost"))
        self.assertTrue(raid["log"])
        with self.assertRaisesRegex(GameError, "already raided today"):
            await self.run_game(war.start_raid, B1, "AAA")

    async def test_rules(self):
        with self.assertRaisesRegex(GameError, "own team"):
            await self.run_game(war.start_raid, A1, "AAA")
        await self.team(C1, "Charlie", "CCC")
        with self.assertRaisesRegex(GameError, "isn't at war"):
            await self.run_game(war.start_raid, A1, "CCC")
        with self.assertRaisesRegex(GameError, "teams at war"):
            await self.run_game(war.start_raid, C1, "AAA")
        self.advance(11 * 3600)  # 23:00
        with self.assertRaisesRegex(GameError, "asleep"):
            await self.run_game(war.start_raid, A1, "BBB")


class ChestBonusTests(WarTestCase):
    async def test_the_leader_picks_it_once_a_week(self):
        with self.assertRaisesRegex(GameError, "leader"):
            await self.run_game(teams.pick_chest_bonus, A2, "trade")
        await self.run_game(teams.pick_chest_bonus, A1, "trade")
        with self.assertRaisesRegex(GameError, "again"):
            await self.run_game(teams.pick_chest_bonus, A1, "mining")
        self.advance(7 * DAY + 60)
        await self.run_game(teams.pick_chest_bonus, A1, "mining")

    async def test_tiers_follow_the_chest(self):
        await self.run_game(teams.pick_chest_bonus, A1, "trade")
        self.assertEqual(await self.run_game(teams.chest_bonus, A2, "trade"), 0.0)  # empty chest
        await self.run_game(players.give_emeralds, A1, 20_000)
        await self.run_game(war.deposit, A1, 20_000)
        self.assertAlmostEqual(await self.run_game(teams.chest_bonus, A2, "trade"), 0.06)  # tier II
        self.assertEqual(await self.run_game(teams.chest_bonus, A2, "mining"), 0.0)  # not the one picked
        self.assertEqual(await self.run_game(teams.chest_bonus, B1, "trade"), 0.0)  # another team
        await self.run_game(players.add_blocks, A2, "cobblestone", 1000)
        res = await self.run_game(players.sell_blocks, A2)
        self.assertEqual(res["bonus"], 60)
        await self.run_game(war.withdraw, A1, 1)  # below 20,000: tier I
        self.assertAlmostEqual(await self.run_game(teams.chest_bonus, A2, "trade"), 0.03)


class LevyTests(WarTestCase):
    async def test_emptying_the_chest_before_monday_doesnt_dodge_it(self):
        await self.run_game(war.weekly)  # the first run sets the week
        await self.run_game(players.give_emeralds, A1, 10_000)
        await self.run_game(war.deposit, A1, 10_000)
        self.advance(7 * DAY - 120)
        await self.run_game(war.withdraw, A1, 10_000)  # emptied 2 minutes before Monday
        self.advance(240)
        res = await self.run_game(war.weekly)
        self.assertEqual(res["pot"], 0)  # nothing to take now…
        debt = await self.run_game(lambda ctx: ctx.one("SELECT chest_debt FROM teams WHERE team_id=?;",
                                                      (self.ta,))["chest_debt"])
        self.assertAlmostEqual(debt, 500, delta=5)  # …but 5% of its average (≈10,000) is owed
        await self.run_game(war.deposit, A1, 2_000)
        self.assertEqual(await self.run_game(war.chest, self.ta), 2_000 - debt)  # the debt is paid first


class DefenseTests(WarTestCase):
    async def test_build_wear_and_repair(self):
        await self.run_game(players.give_emeralds, A1, 50_000)
        await self.run_game(war.deposit, A1, 30_000)
        with self.assertRaisesRegex(GameError, "leader"):
            await self.run_game(war.buy_defense, A2, "golem")
        res = await self.run_game(war.buy_defense, A1, "golem")
        self.assertEqual((res["level"], res["chest"]), (1, 22_000))
        await self.run_game(war.buy_defense, A1, "walls")
        # A raid with nobody but the golem defending: the fight starts anyway.
        raid = await self.run_game(war.start_raid, B1, "AAA")
        await self.run_game(war.join_raid, raid["raid_id"], B2)
        await self.run_game(war.launch_raid, raid["raid_id"], B1)
        raid = await self.run_game(war.resolve_raid, raid["raid_id"])
        fight = war.fight_of(raid)
        self.assertEqual((raid["status"], fight.walls), ("fighting", 0.04))
        self.assertTrue(any(f.golem for f in fight.fighters))
        await self.run_game(war.play_out, raid["raid_id"])
        d = await self.run_game(war.defenses, self.ta)
        self.assertEqual((d["golem"], d["walls"]), ([1, 0.75], [1, 0.75]))
        res = await self.run_game(war.repair_defense, A1, "golem")
        self.assertEqual(res["price"], round(8_000 * 0.25 * 0.25))
        for _ in range(4):  # 4 raids wear a level away
            await self.run_game(lambda ctx: war._wear_defenses(ctx, self.ta))
        self.assertEqual((await self.run_game(war.defenses, self.ta))["walls"], [0, 1.0])


class RaidFightTests(WarTestCase):
    async def test_a_player_who_doesnt_play_attacks_then_plays_by_themselves(self):
        raid = await self.run_game(war.start_raid, B1, "AAA")
        await self.run_game(war.join_raid, raid["raid_id"], B2)
        await self.run_game(war.launch_raid, raid["raid_id"], B1)
        await self.run_game(war.join_raid, raid["raid_id"], A1)
        raid = await self.run_game(war.resolve_raid, raid["raid_id"])
        first = war.fight_of(raid).current.user_id
        self.advance(31)
        [raid] = await self.run_game(war.due_raids)
        if raid["status"] == "fighting":
            fight = war.fight_of(raid)
            self.assertEqual(next(f for f in fight.fighters if f.user_id == first).afk, 1)
            await self.run_game(war.raid_present, raid["raid_id"], first)
            fight = war.fight_of(await self.run_game(war.get_raid, raid["raid_id"]))
            self.assertEqual(next(f for f in fight.fighters if f.user_id == first).afk, 0)
