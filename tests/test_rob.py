"""Robberies and the small bot state store."""
from __future__ import annotations

from game import botstate, players, robbery, settings
from game.errors import GameError
from tests.helpers import GameTestCase

THIEF, VICTIM, OTHER = 1, 2, 3
HOUR = 3600


class RobTests(GameTestCase):
    # Reaching level 10 below would pay the "level_10" achievement: keep the balances simple.
    overrides = {"achievements": {"level_10": {"goal": 10, "reward": 0}}}

    async def asyncSetUp(self):
        await super().asyncSetUp()
        for uid in (THIEF, VICTIM, OTHER):
            await self.run_game(players.set_level, uid, 10)
        await self.run_game(players.give_emeralds, VICTIM, 1000)
        await self.run_game(players.give_emeralds, THIEF, 100)

    async def test_a_robbery_nobody_stops(self):
        rob = await self.run_game(robbery.start, THIEF, VICTIM, "risky")
        self.assertTrue(200 <= rob["amount"] <= 500)
        self.assertEqual(rob["ends_at"] - rob["started_at"], HOUR)
        self.assertEqual(await self.run_game(robbery.finish_due), [])  # not yet
        self.advance(HOUR)
        done = await self.run_game(robbery.finish_due)
        self.assertEqual((len(done), done[0]["stolen"]), (1, rob["amount"]))
        self.assertEqual(await self.run_game(players.get_emeralds, THIEF), 100 + rob["amount"])
        self.assertEqual(await self.run_game(players.get_emeralds, VICTIM), 1000 - rob["amount"])
        self.assertEqual(await self.run_game(players.get_stat, THIEF, "emeralds_earned"), 0)  # not for the seasons

    async def test_never_more_than_the_victim_has(self):
        await self.run_game(players.set_level, OTHER, 10)
        await self.run_game(players.give_emeralds, OTHER, 30)
        rob = await self.run_game(robbery.start, THIEF, OTHER, "discreet")
        self.assertTrue(50 <= rob["amount"] <= 100)
        self.advance(HOUR)
        self.assertEqual((await self.run_game(robbery.finish_due))[0]["stolen"], 30)

    async def test_the_victim_stops_it_and_gets_a_fine(self):
        rob = await self.run_game(robbery.start, THIEF, VICTIM, "risky")
        with self.assertRaisesRegex(GameError, "Only"):
            await self.run_game(robbery.stop, rob["rob_id"], OTHER)
        self.advance(HOUR - 60)
        stopped = await self.run_game(robbery.stop, rob["rob_id"], VICTIM)
        self.assertEqual(stopped["fine"], robbery.fine_for(rob["amount"]))
        self.assertEqual(await self.run_game(players.get_emeralds, VICTIM), 1000 + stopped["fine"])
        self.advance(120)
        self.assertEqual(await self.run_game(robbery.finish_due), [])
        with self.assertRaisesRegex(GameError, "over"):
            await self.run_game(robbery.stop, rob["rob_id"], VICTIM)

    async def test_too_late_to_stop(self):
        rob = await self.run_game(robbery.start, THIEF, VICTIM, "discreet")
        self.advance(HOUR)
        with self.assertRaisesRegex(GameError, "Too late"):
            await self.run_game(robbery.stop, rob["rob_id"], VICTIM)

    async def test_the_fine_is_never_more_than_the_thief_has(self):
        settings.load({"rob": {"fine_percent": 1000}})
        rob = await self.run_game(robbery.start, THIEF, VICTIM, "risky")
        stopped = await self.run_game(robbery.stop, rob["rob_id"], VICTIM)
        self.assertEqual(stopped["fine"], 100)
        self.assertEqual(await self.run_game(players.get_emeralds, THIEF), 0)

    async def test_rules(self):
        with self.assertRaisesRegex(GameError, "yourself"):
            await self.run_game(robbery.start, THIEF, THIEF, "risky")
        await self.run_game(players.set_level, OTHER, 4)
        with self.assertRaisesRegex(GameError, "below level"):
            await self.run_game(robbery.start, THIEF, OTHER, "risky")
        await self.run_game(robbery.start, THIEF, VICTIM, "risky")
        with self.assertRaisesRegex(GameError, "already robbing"):
            await self.run_game(robbery.start, OTHER, VICTIM, "discreet")
        with self.assertRaisesRegex(GameError, "rob again in"):
            await self.run_game(robbery.start, THIEF, VICTIM, "risky")
        self.advance(HOUR)
        await self.run_game(robbery.finish_due)
        # The victim is protected for 12 h, the thief waits 6 h.
        await self.run_game(players.set_level, OTHER, 10)
        await self.run_game(players.give_emeralds, OTHER, 50)
        with self.assertRaisesRegex(GameError, "protected"):
            await self.run_game(robbery.start, OTHER, VICTIM, "risky")
        self.advance(5 * HOUR)
        await self.run_game(robbery.start, THIEF, OTHER, "discreet")  # 6 h after the start
        self.advance(7 * HOUR)
        await self.run_game(robbery.start, OTHER, VICTIM, "risky")  # 13 h after the robbery

    async def test_nothing_to_steal(self):
        await self.run_game(players.give_emeralds, OTHER, 0)
        with self.assertRaisesRegex(GameError, "no emeralds"):
            await self.run_game(robbery.start, THIEF, OTHER, "risky")


class BotStateTests(GameTestCase):
    async def test_get_put(self):
        self.assertIsNone(await self.run_game(botstate.get, "x"))
        await self.run_game(botstate.put, "x", "1:2")
        await self.run_game(botstate.put, "x", "3:4")
        self.assertEqual(await self.run_game(botstate.get, "x"), "3:4")
        await self.run_game(botstate.put, "x", None)
        self.assertIsNone(await self.run_game(botstate.get, "x"))
