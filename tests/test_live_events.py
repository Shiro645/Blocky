"""Timed events: starting and ending them, the daily random one, and what each one changes."""
from __future__ import annotations

from game import gambling, live_events, luckyblock, mining, players, shop, species
from game.errors import GameError
from tests.helpers import DAY, GameTestCase

ALICE, BOB = 1, 2
MINUTE = 60


class LiveEventTests(GameTestCase):
    async def test_start_and_stop(self):
        self.assertIsNone(await self.run_game(live_events.current))
        event = await self.run_game(live_events.start, "golden_hour", None, 99)
        self.assertEqual(event["ends_at"] - event["starts_at"], 60 * MINUTE)
        self.assertEqual((await self.run_game(live_events.current))["kind"], "golden_hour")
        with self.assertRaisesRegex(GameError, "end it first"):
            await self.run_game(live_events.start, "mining_rush")
        await self.run_game(live_events.stop)
        self.assertIsNone(await self.run_game(live_events.current))
        with self.assertRaisesRegex(GameError, "No event"):
            await self.run_game(live_events.stop)
        await self.run_game(live_events.start, "mining_rush", 5)
        self.advance(5 * MINUTE)
        self.assertIsNone(await self.run_game(live_events.current))

    async def test_announced_then_ended(self):
        event = await self.run_game(live_events.start, "lucky_hour", 10)
        self.assertEqual([e["event_id"] for e in await self.run_game(live_events.to_announce)], [event["event_id"]])
        await self.run_game(live_events.set_message, event["event_id"], 5, 6)
        self.assertEqual(await self.run_game(live_events.to_announce), [])
        self.advance(10 * MINUTE)
        self.assertEqual([c["type"] for c in await self.run_game(live_events.tick)
                          if c["event"]["event_id"] == event["event_id"]], ["ended"])
        self.assertEqual(await self.run_game(live_events.tick), [])  # only once

    async def test_one_random_event_a_day(self):
        at = await self.run_game(live_events.random_time)
        self.now = at - MINUTE
        self.assertEqual(await self.run_game(live_events.tick), [])
        self.now = at
        started = await self.run_game(live_events.tick)
        self.assertEqual([c["type"] for c in started], ["started"])
        first = started[0]["event"]["kind"]
        self.advance(2 * 60 * MINUTE)
        self.assertEqual([c["type"] for c in await self.run_game(live_events.tick)], [])  # ended unannounced
        # The next day: another one, and not the same as yesterday's.
        self.now = await self.run_game(live_events.random_time, self.today_plus(1))
        nxt = await self.run_game(live_events.tick)
        self.assertNotEqual(nxt[0]["event"]["kind"], first)

    def today_plus(self, days: int):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        return datetime.fromtimestamp(self.now + days * DAY, ZoneInfo("Europe/Paris")).date()

    async def test_today(self):
        at = await self.run_game(live_events.random_time)
        self.now = at - MINUTE
        self.assertEqual((await self.run_game(live_events.today))["status"], "coming")
        self.now = at
        await self.run_game(live_events.tick)
        day = await self.run_game(live_events.today)
        self.assertEqual((day["status"], day["event"]["starts_at"]), ("on", int(at)))
        self.advance(61 * MINUTE)
        self.assertEqual((await self.run_game(live_events.today))["status"], "passed")

    async def test_no_random_event_when_turned_off(self):
        from game import settings

        settings.load({"live_events": {"daily_random": False}})
        self.assertIsNone(await self.run_game(live_events.random_time))
        self.now += DAY / 2
        self.assertEqual(await self.run_game(live_events.tick), [])


class EventBonusTests(GameTestCase):
    async def test_gambling_frenzy(self):
        for uid in (ALICE, BOB):
            await self.run_game(players.give_emeralds, uid, 10_000)
        await self.run_game(species.choose, BOB, "gambler")
        self.assertEqual(await self.run_game(gambling.max_bet, ALICE), 200)
        await self.run_game(live_events.start, "gambling_frenzy")
        self.assertEqual(await self.run_game(gambling.max_bet, ALICE), 400)
        self.assertEqual(await self.run_game(gambling.max_bet, BOB), 600)  # Gambler on top
        self.assertEqual(await self.run_game(gambling.daily_cap), 3000)
        await self.run_game(luckyblock.open_block, ALICE, 400)
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "frenzy_games"), 1)
        await self.run_game(live_events.stop)
        with self.assertRaisesRegex(GameError, "200"):
            await self.run_game(luckyblock.open_block, ALICE, 400)

    async def test_mining_rush_and_lucky_hour(self):
        normal = mining.pile_weights(1, 0, 0)
        lucky = mining.pile_weights(1, 0, 0, 2.0)
        self.assertEqual(lucky["bedrock"], normal["bedrock"] * 2)
        self.assertEqual(lucky["obsidian"], normal["obsidian"] * 2)
        self.assertEqual(lucky["cobblestone"], normal["cobblestone"])
        self.assertEqual(await self.run_game(live_events.xp_multiplier), 1.0)
        await self.run_game(live_events.start, "mining_rush")
        self.assertEqual(await self.run_game(live_events.xp_multiplier), 2.0)
        self.assertEqual((await self.run_game(mining.mine, ALICE))["rush"], 2.0)
        self.assertEqual(await self.run_game(live_events.rare_multiplier), 1.0)

    async def test_golden_hour(self):
        await self.run_game(players.add_blocks, ALICE, "bedrock", 10)
        await self.run_game(live_events.start, "golden_hour")
        res = await self.run_game(players.sell_blocks, ALICE)
        self.assertEqual((res["base"], res["bonus"]), (100, 50))
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 150)

    async def test_market_sale(self):
        await self.run_game(players.give_emeralds, ALICE, 1000)
        await self.run_game(live_events.start, "market_sale")
        res = await self.run_game(shop.buy, ALICE, "diamond_ingot", 2)
        self.assertEqual((res["price"], res["saved"], res["sale"]), (90, 30, 0.25))
        self.assertEqual(shop.sale_price(60, 0.25), 45)
        # Gear sells for what its ingots cost now: buying cheap to craft and sell back is no profit.
        gid = await self.run_game(shop.create_gear, ALICE, "sword", "diamond")
        piece = await self.run_game(shop.owned_piece, ALICE, gid)
        offer = await self.run_game(shop.gear_offer, ALICE, piece)
        self.assertLess(offer["price"], 90)
