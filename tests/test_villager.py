from __future__ import annotations

import random
import unittest

from game import duel, enchants, players, potions, seasons, settings, villager
from game.errors import GameError
from tests.helpers import DAY, GameTestCase

HOUR = 3600
ALICE, BOB = 1, 2


class VillagerTestCase(GameTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.start = self.now  # Wednesday 12:00

    async def tick(self) -> list[dict]:
        return await self.run_game(villager.tick)

    async def visit_now(self) -> dict:
        self.now = self.start + 6 * HOUR  # 18:00
        return (await self.tick())[0]["visit"]


class ScheduleTests(VillagerTestCase):
    async def test_comes_at_18_and_leaves_at_21(self):
        self.assertEqual(await self.tick(), [])
        self.assertEqual(await self.run_game(villager.next_arrival), int(self.start + 6 * HOUR))
        visit = await self.visit_now()
        self.assertEqual(visit["leaves_at"], int(self.start + 9 * HOUR))
        self.assertEqual([o["kind"] for o in visit["offers"]], ["sell", "buy", "exclusive"])
        self.assertEqual(await self.tick(), [])  # only once
        self.now = self.start + 9 * HOUR
        events = await self.tick()
        self.assertEqual([e["type"] for e in events], ["left"])
        self.assertIsNone(await self.run_game(villager.current))
        self.now = self.start + 10 * HOUR
        self.assertEqual(await self.tick(), [])  # not back the same evening
        self.now = self.start + DAY + 6 * HOUR
        self.assertEqual([e["type"] for e in await self.tick()], ["arrived"])

    async def test_staff_visit_does_not_cancel_the_evening(self):
        visit = await self.run_game(villager.arrive)  # 12:00, stays 3 hours
        self.assertEqual(visit["leaves_at"], int(self.start + 3 * HOUR))
        with self.assertRaisesRegex(GameError, "already here"):
            await self.run_game(villager.arrive)
        await self.run_game(villager.leave_now)
        self.now = self.start + 6 * HOUR
        self.assertEqual([e["type"] for e in await self.tick()], ["arrived"])


class OfferTests(VillagerTestCase):
    async def test_offer_prices(self):
        for _ in range(20):
            visit = await self.run_game(villager.arrive)
            sell, buy, exclusive = visit["offers"]
            self.assertEqual(sell["price"], max(1, round(sell["value"] * 0.7)))
            self.assertFalse(sell["asset"].endswith(":3"))  # level III books are exclusive
            self.assertEqual(buy["price"], round(buy["value"] * 1.5))
            self.assertTrue(buy["asset"].startswith("block:"))
            self.assertTrue(exclusive["asset"].endswith(":3") or exclusive["asset"].endswith(":2"))
            await self.run_game(villager.leave_now)

    async def test_buying_an_offer_once(self):
        visit = await self.visit_now()
        sell = visit["offers"][0]
        await self.run_game(players.give_emeralds, ALICE, sell["price"])
        await self.run_game(players.give_emeralds, BOB, 10_000)
        res = await self.run_game(villager.take, ALICE, visit["visit_id"], 0)
        self.assertEqual(res["offer"]["taken_by"], ALICE)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 0)
        with self.assertRaisesRegex(GameError, "Too late"):
            await self.run_game(villager.take, BOB, visit["visit_id"], 0)
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "villager_trades"), 1)

    async def test_selling_blocks_counts_as_earned(self):
        visit = await self.visit_now()
        buy = visit["offers"][1]
        block = buy["asset"].split(":")[1]
        with self.assertRaisesRegex(GameError, "don't have"):
            await self.run_game(villager.take, ALICE, visit["visit_id"], 1)
        await self.run_game(players.add_blocks, ALICE, block, buy["amount"])
        await self.run_game(villager.take, ALICE, visit["visit_id"], 1)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), buy["price"])
        self.assertEqual((await self.run_game(seasons.overview, ALICE))["score"], buy["price"])
        self.assertEqual((await self.run_game(players.get_blocks, ALICE))[block], 0)

    async def test_exclusive_goes_to_the_inventory(self):
        visit = await self.visit_now()
        exclusive = visit["offers"][2]
        await self.run_game(players.give_emeralds, ALICE, exclusive["price"])
        await self.run_game(villager.take, ALICE, visit["visit_id"], 2)
        kind, *rest = exclusive["asset"].split(":")
        if kind == "book":
            self.assertEqual(await self.run_game(enchants.books, ALICE), [(rest[0], 3, 1)])
        else:
            self.assertEqual(await self.run_game(potions.owned, ALICE), {f"{rest[0]}:2": 1})

    async def test_cannot_buy_after_he_left(self):
        visit = await self.visit_now()
        await self.run_game(players.give_emeralds, ALICE, 10_000)
        self.now = self.start + 9 * HOUR
        with self.assertRaisesRegex(GameError, "left"):
            await self.run_game(villager.take, ALICE, visit["visit_id"], 0)


class PotionLevelTests(unittest.TestCase):
    def setUp(self):
        settings.load({"duel": {"crit_chance": 0}})

    def test_reinforced_potions(self):
        self.assertEqual(potions.label("healing:2"), "Potion of Healing II")
        self.assertEqual(potions.effect("healing:2", "healing_hp"), 12)
        self.assertEqual(potions.value("speed:2"), 120)
        for bad in ("healing:3", "magic", "healing:x"):
            with self.subTest(bad=bad), self.assertRaises(GameError):
                potions.parse(bad)

    def test_strength_ii_doubles_the_bonus(self):
        a = duel.Fight(random.Random(5), duel.Fighter(ALICE, 10, 0, 20), duel.Fighter(BOB, 10, 0, 20))
        b = duel.Fight(random.Random(5), duel.Fighter(ALICE, 10, 0, 20), duel.Fighter(BOB, 10, 0, 20))
        plain = a.play(random.Random(7)).hits[0].damage
        boosted = b.play(random.Random(7), "strength:2").hits[0].damage
        self.assertAlmostEqual(boosted, plain * 2)


if __name__ == "__main__":
    unittest.main()
