"""Gate bosses (2.0.2): groups, turns, the bosses' attacks, rewards and the dimensions they open."""
from __future__ import annotations

import random

from game import cooldowns, dimensions, gate, gear, players, potions, settings, shop
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB, CAROL = 1, 2, 3
HOUR = 3600


def set_boss_hp(ctx, fight_id: int, hp: float) -> None:
    row = gate.get(ctx, fight_id)
    fight = row["fight"]
    fight.hp = hp
    ctx.execute("UPDATE gate_fights SET state=? WHERE fight_id=?;", (fight.to_json(), fight_id))


class GateTestCase(GameTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for uid in (ALICE, BOB, CAROL):
            await self.run_game(players.give_emeralds, uid, 20_000)
            await self.run_game(dimensions.set_highest, uid, "nether")

    async def group(self, *uids: int, boss: str = "wither") -> int:
        row = await self.run_game(gate.create, uids[0], boss)
        for uid in uids[1:]:
            await self.run_game(gate.join, row["fight_id"], uid)
        await self.run_game(gate.start, row["fight_id"], uids[0])
        return row["fight_id"]


class LobbyTests(GateTestCase):
    async def test_entry_requirements_and_refunds(self):
        await self.run_game(dimensions.set_highest, CAROL, "overworld")
        with self.assertRaisesRegex(GameError, "hasn't reached"):
            await self.run_game(gate.create, CAROL, "wither")
        with self.assertRaisesRegex(GameError, "hasn't reached"):
            await self.run_game(gate.create, ALICE, "ender_dragon")
        row = await self.run_game(gate.create, ALICE, "wither")
        await self.run_game(gate.join, row["fight_id"], BOB)
        self.assertEqual(await self.run_game(players.get_emeralds, BOB), 20_000 - 1500)
        with self.assertRaisesRegex(GameError, "already in a boss fight"):
            await self.run_game(gate.create, BOB, "wither")
        with self.assertRaisesRegex(GameError, "Only the group's leader"):
            await self.run_game(gate.start, row["fight_id"], BOB)
        await self.run_game(gate.leave_lobby, row["fight_id"], ALICE)  # the leader leaves: cancelled
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 20_000)
        self.assertEqual(await self.run_game(players.get_emeralds, BOB), 20_000)
        self.assertEqual((await self.run_game(gate.get, row["fight_id"]))["status"], "cancelled")

    async def test_a_lobby_not_started_is_cancelled(self):
        row = await self.run_game(gate.create, ALICE, "wither")
        self.advance(6 * 60)
        out = await self.run_game(gate.expire)
        self.assertEqual(out[0]["status"], "cancelled")
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 20_000)
        self.assertEqual(await self.run_game(gate.ready_at, ALICE), 0)  # never started: no cooldown
        del row

    async def test_full_group(self):
        settings.load({"gate_bosses": {"max_players": 2}})
        row = await self.run_game(gate.create, ALICE, "wither")
        await self.run_game(gate.join, row["fight_id"], BOB)
        with self.assertRaisesRegex(GameError, "full"):
            await self.run_game(gate.join, row["fight_id"], CAROL)


class FightTests(GateTestCase):
    async def test_turns_in_order_then_the_boss(self):
        fid = await self.group(ALICE, BOB)
        with self.assertRaisesRegex(GameError, "turn"):
            await self.run_game(gate.attack, fid, BOB)
        row = await self.run_game(gate.attack, fid, ALICE)
        self.assertEqual(row["fight"].current.user_id, BOB)
        self.assertEqual(row["fight"].rounds, 0)
        row = await self.run_game(gate.attack, fid, BOB)
        self.assertEqual((row["fight"].current.user_id, row["fight"].rounds), (ALICE, 1))  # the boss played
        self.assertTrue(any("Wither blasts" in line for line in row["fight"].log))

    async def test_a_small_group_faces_less_health(self):
        fid = await self.group(ALICE, BOB)
        row = await self.run_game(gate.get, fid)
        self.assertAlmostEqual(row["fight"].max_hp, 400 * 0.59)

    async def test_no_move_in_time(self):
        fid = await self.group(ALICE, BOB)
        self.advance(31)
        await self.run_game(gate.expire)
        row = await self.run_game(gate.get, fid)
        self.assertEqual(row["fight"].current.user_id, BOB)
        self.assertEqual(row["fight"].player(ALICE).afk, 1)
        await self.run_game(gate.attack, fid, BOB)
        self.advance(31)
        row = (await self.run_game(gate.expire))[0]  # Alice's second miss: her turns play by themselves now
        self.assertEqual(row["fight"].player(ALICE).afk, 2)
        self.assertEqual(row["fight"].current.user_id, BOB)
        await self.run_game(gate.present, fid, ALICE)  # she clicks (out of turn): she's back in control
        row = await self.run_game(gate.attack, fid, BOB)
        self.assertEqual((row["fight"].current.user_id, row["fight"].player(ALICE).afk), (ALICE, 0))

    async def test_drinking_then_running_out_of_time_isnt_a_missed_turn(self):
        fid = await self.group(ALICE, BOB)
        await self.run_game(potions.give, ALICE, "harming", 1)
        await self.run_game(gate.drink, fid, ALICE, "harming")
        self.advance(31)
        row = (await self.run_game(gate.expire))[0]
        self.assertEqual(row["fight"].player(ALICE).afk, 0)

    async def test_potions_two_per_fight(self):
        fid = await self.group(ALICE)
        await self.run_game(potions.give, ALICE, "harming", 3)
        await self.run_game(gate.drink, fid, ALICE, "harming")
        with self.assertRaisesRegex(GameError, "already drank a potion this turn"):
            await self.run_game(gate.drink, fid, ALICE, "harming")
        await self.run_game(gate.attack, fid, ALICE)
        await self.run_game(gate.drink, fid, ALICE, "harming")
        await self.run_game(gate.attack, fid, ALICE)
        with self.assertRaisesRegex(GameError, "2 potions"):
            await self.run_game(gate.drink, fid, ALICE, "harming")
        self.assertEqual(await self.run_game(potions.owned, ALICE), {"harming": 1})

    async def test_the_shield_blocks_the_next_hit(self):
        gid = await self.run_game(shop.create_gear, ALICE, "shield", "iron")
        await self.run_game(gear.equip, ALICE, gid)
        fid = await self.group(ALICE)
        row = await self.run_game(gate.attack, fid, ALICE, True)
        alice = row["fight"].player(ALICE)
        self.assertEqual((alice.hp, alice.blocks_used, alice.withered), (20.0, 1, 0))
        self.assertTrue(any("blocked" in line for line in row["fight"].log))
        with self.assertRaisesRegex(GameError, "need a shield"):
            fid2 = await self.group(BOB)
            await self.run_game(gate.attack, fid2, BOB, True)

    def test_the_dragon_and_the_warden(self):
        rng = random.Random(1)
        heroes = [gate.Player(i, 10, 1, 0.0, 20.0) for i in (1, 2, 3)]
        fight = gate.new_fight("ender_dragon", heroes)
        for _ in range(3):
            fight.boss_turn(rng)
        self.assertTrue(any("breathes fire" in line for line in fight.log))  # the 3rd turn
        heroes = [gate.Player(i, 10, 1, 0.9, 200.0, blocks_left=9, blocking=True) for i in (1, 2)]
        fight = gate.new_fight("warden", heroes)
        for _ in range(4):
            fight.boss_turn(rng)
        boom = [line for line in fight.log if "Sonic Boom" in line][0]
        self.assertNotIn("blocked", boom)  # armor and the shield don't stop it


class RewardTests(GateTestCase):
    async def test_survivors_open_the_next_dimension(self):
        fid = await self.group(ALICE, BOB)
        await self.run_game(gate.attack, fid, ALICE)
        await self.run_game(set_boss_hp, fid, 0.5)
        await self.run_game(lambda ctx: ctx.execute("UPDATE users SET emeralds=0 WHERE user_id=?;", (BOB,)))
        row = await self.run_game(gate.attack, fid, BOB)
        self.assertEqual(row["status"], "won")
        self.assertEqual(set(row["rewards"]), {ALICE, BOB})
        self.assertEqual(row["rewards"][BOB]["opened"], "end")
        self.assertEqual(await self.run_game(players.get_emeralds, BOB), 3000 + 1000 + 100)  # + Wither and Boss Slayer
        self.assertTrue(await self.run_game(dimensions.has, BOB, "end"))
        self.assertEqual(await self.run_game(players.get_stat, BOB, "wither_defeated"), 1)

    async def test_the_fallen_get_nothing_and_a_second_win_pays_less(self):
        fid = await self.group(ALICE, BOB)

        def kill_bob(ctx):
            row = gate.get(ctx, fid)
            row["fight"].player(BOB).hp = 0
            ctx.execute("UPDATE gate_fights SET state=? WHERE fight_id=?;", (row["fight"].to_json(), fid))

        await self.run_game(kill_bob)
        await self.run_game(set_boss_hp, fid, 0.5)
        row = await self.run_game(gate.attack, fid, ALICE)
        self.assertEqual(list(row["rewards"]), [ALICE])
        self.assertFalse(await self.run_game(dimensions.has, BOB, "end"))
        # Alice fights the Wither again after her cooldown: she had already opened the End.
        self.advance(13 * HOUR)
        fid = await self.group(ALICE)
        await self.run_game(set_boss_hp, fid, 0.5)
        row = await self.run_game(gate.attack, fid, ALICE)
        self.assertEqual((row["rewards"][ALICE]["opened"], row["rewards"][ALICE]["bounty"]), (None, 750))

    async def test_cooldown_and_staff_reset(self):
        fid = await self.group(ALICE)
        await self.run_game(set_boss_hp, fid, 0.5)
        await self.run_game(gate.attack, fid, ALICE)
        with self.assertRaisesRegex(GameError, "recovering"):
            await self.run_game(gate.create, ALICE, "wither")
        await self.run_game(cooldowns.reset, ALICE, ["boss"])
        await self.run_game(gate.create, ALICE, "wither")

    async def test_a_lost_fight(self):
        fid = await self.group(ALICE)

        def nearly_dead(ctx):
            row = gate.get(ctx, fid)
            row["fight"].player(ALICE).hp = 0.1
            ctx.execute("UPDATE gate_fights SET state=? WHERE fight_id=?;", (row["fight"].to_json(), fid))

        await self.run_game(nearly_dead)
        row = await self.run_game(gate.attack, fid, ALICE)
        self.assertEqual((row["status"], row["rewards"]), ("lost", {}))
        self.assertFalse(await self.run_game(dimensions.has, ALICE, "end"))


class NightmareTests(GameTestCase):
    async def test_the_nightmare_opens_the_nether(self):
        from game import pve

        await self.run_game(players.give_emeralds, ALICE, 5000)
        run = await self.run_game(pve.create, ALICE, "nightmare")
        await self.run_game(lambda ctx: ctx.execute("UPDATE pve_runs SET wave=4 WHERE run_id=?;", (run["run_id"],)))
        settings.load({"pve": {"difficulties": {"nightmare": {"strength": 0.001}}}})
        res = await self.run_game(pve.start, run["run_id"], ALICE)
        self.assertTrue(res["cleared_all"])
        self.assertEqual(res["nether"], [ALICE])
        self.assertTrue(await self.run_game(dimensions.has, ALICE, "nether"))
