"""The server's Beacon (2.0.3): lit by the Wither, built in steps by everyone, its effects and its upkeep."""
from __future__ import annotations

from game import beacon, dimensions, gate, mining, players, pve, settings
from game.errors import GameError
from tests.helpers import DAY, GameTestCase
from tests.test_gate import set_boss_hp

ALICE, BOB = 1, 2


class BeaconTests(GameTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for uid in (ALICE, BOB):
            for m in beacon.ORDER:
                await self.run_game(players.add_item, uid, "ingot", m, 3000)

    async def light(self):
        await self.run_game(beacon.light, ALICE)

    async def test_lit_by_the_first_wither(self):
        with self.assertRaisesRegex(GameError, "Nether Star"):
            await self.run_game(beacon.give, ALICE, "gold", 9)
        await self.run_game(players.give_emeralds, ALICE, 5000)
        await self.run_game(dimensions.set_highest, ALICE, "nether")
        row = await self.run_game(gate.create, ALICE, "wither")
        await self.run_game(gate.start, row["fight_id"], ALICE)
        await self.run_game(set_boss_hp, row["fight_id"], 0.5)
        row = await self.run_game(gate.attack, row["fight_id"], ALICE)
        self.assertTrue(row["beacon_lit"])
        self.assertTrue(await self.run_game(beacon.is_lit))
        self.advance(13 * 3600)
        row = await self.run_game(gate.create, ALICE, "wither")
        await self.run_game(gate.start, row["fight_id"], ALICE)
        await self.run_game(set_boss_hp, row["fight_id"], 0.5)
        self.assertFalse((await self.run_game(gate.attack, row["fight_id"], ALICE))["beacon_lit"])  # once

    async def test_whole_blocks_and_the_right_material(self):
        await self.light()
        with self.assertRaisesRegex(GameError, "multiple of 9"):
            await self.run_game(beacon.give, ALICE, "gold", 10)
        with self.assertRaisesRegex(GameError, "81 gold ingots for level 1"):
            await self.run_game(beacon.give, ALICE, "iron", 9)
        res = await self.run_game(beacon.give, ALICE, "gold", 90)  # level 1 (81) and 9 toward level 2
        self.assertEqual(res["built"], [("gold", 1)])
        st = res["status"]
        self.assertEqual((st["step"], st["progress"], st["next"]), (1, 9, ("gold", 2)))
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "gold"), 3000 - 90)

    async def test_gold_first_then_level_by_level(self):
        await self.light()
        await self.run_game(beacon.give, ALICE, "gold", 81 + 225 + 441 + 729)
        st = await self.run_game(beacon.status)
        self.assertEqual(st["levels"], {1: "gold", 2: "gold", 3: "gold", 4: "gold"})
        await self.run_game(beacon.give, BOB, "iron", 81)
        st = await self.run_game(beacon.status)
        self.assertEqual(st["levels"], {1: "iron", 2: "gold", 3: "gold", 4: "gold"})
        e = st["effects"]
        self.assertAlmostEqual(e["haste"], 0.05 * 1.5)
        self.assertAlmostEqual(e["sell"], 0.05)
        self.assertAlmostEqual(e["resistance"], 0.015)

    async def test_effects_reach_mining_selling_and_fights(self):
        await self.light()
        await self.run_game(beacon.give, ALICE, "gold", 81 + 225 + 441 + 729)
        res = await self.run_game(mining.mine, BOB)
        self.assertEqual(res["cooldown"], round(30 * 0.95))
        await self.run_game(players.add_blocks, BOB, "bedrock", 100)
        sold = await self.run_game(players.sell_blocks, BOB, "bedrock")
        self.assertEqual(sold["bonus"], round(1000 * 0.05))
        hero = await self.run_game(pve.make_hero, BOB)
        self.assertAlmostEqual(hero.attack, 6 * 1.015)  # no sword: 6, +1.5%
        self.assertAlmostEqual(hero.reduction, 0.015)

    async def test_contributor_bonus(self):
        await self.light()
        self.assertFalse(await self.run_game(beacon.contributor, ALICE))
        await self.run_game(beacon.give, ALICE, "gold", 45)  # 225 emeralds' worth
        self.assertTrue(await self.run_game(beacon.contributor, ALICE))
        self.assertAlmostEqual(await self.run_game(beacon.sell_bonus, ALICE), 0.05)
        self.advance(7 * DAY)
        self.assertFalse(await self.run_game(beacon.contributor, ALICE))  # a new week

    async def test_upkeep_or_the_last_step_crumbles(self):
        await self.light()
        await self.run_game(beacon.give, ALICE, "gold", 81 + 225)
        st = await self.run_game(beacon.status)
        # 5% of 225, whole blocks; building a step covers the week's upkeep
        self.assertEqual((st["upkeep_material"], st["upkeep_due"], st["upkeep_paid"]), ("gold", 18, 18))
        self.advance(7 * DAY)
        self.assertIsNone((await self.run_game(beacon.weekly))["undone"])
        await self.run_game(beacon.give, BOB, "gold", 27)  # this week: the upkeep first, then 9 toward level 3
        st = await self.run_game(beacon.status)
        self.assertEqual((st["upkeep_paid"], st["progress"]), (18, 9))
        self.advance(7 * DAY)
        self.assertIsNone((await self.run_game(beacon.weekly))["undone"])
        self.advance(7 * DAY)  # nobody gave this time
        res = await self.run_game(beacon.weekly)
        self.assertEqual(res["undone"], ("gold", 2))
        self.assertEqual((await self.run_game(beacon.status))["step"], 1)

    async def test_staff_and_settings(self):
        st = await self.run_game(beacon.staff_set, True, 8)
        self.assertEqual(st["levels"], {1: "iron", 2: "iron", 3: "iron", 4: "iron"})
        st = await self.run_game(beacon.staff_set, False)
        self.assertFalse(st["lit"])
        self.assertEqual((await self.run_game(beacon.effects))["haste"], 0)
        self.assertTrue(settings.problems({"beacon": {"level_ingots": [80, 225, 441, 729]}}))
