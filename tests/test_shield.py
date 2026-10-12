"""The shield: iron only, blocks hits in duels and the tournament, 2 fights then /repair."""
from __future__ import annotations

from game import assets, duel, enchants, gear, players, settings, shop, tournament
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2


class ShieldTests(GameTestCase):
    async def craft_shield(self, uid=ALICE) -> dict:
        await self.run_game(players.add_item, uid, "ingot", "iron", 6)
        res = await self.run_game(shop.craft, uid, "shield", "iron")
        return (await self.run_game(gear.get_equipped, uid))["shield"] | {"crafted": res}

    async def test_craft_iron_only(self):
        await self.run_game(players.add_item, ALICE, "ingot", "gold", 6)
        with self.assertRaisesRegex(GameError, "only be made of iron"):
            await self.run_game(shop.craft, ALICE, "shield", "gold")
        await self.run_game(players.add_item, ALICE, "ingot", "iron", 5)
        with self.assertRaisesRegex(GameError, "Missing"):
            await self.run_game(shop.craft, ALICE, "shield", "iron")
        shield = await self.craft_shield()
        self.assertEqual((shield["durability"], shield["max_durability"], shield["crafted"]["equipped"]), (100, 100, True))
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "iron"), 5)
        assets.parse("gear:iron:shield")
        with self.assertRaises(GameError):
            assets.parse("gear:gold:shield")
        self.assertIn("gear:iron:shield", assets.catalog())

    async def test_blocks_hits_two_duels_then_repair(self):
        await self.craft_shield()
        alice, _ = await self.run_game(duel.make_fighter, ALICE)
        bob, _ = await self.run_game(duel.make_fighter, BOB)
        self.assertEqual((alice.block_chance, bob.block_chance), (0.25, 0.0))
        for uid in (ALICE, BOB):
            await self.run_game(players.give_emeralds, uid, 1000)
        first = await self.run_game(duel.fight, ALICE, BOB, 10)
        self.assertEqual((await self.run_game(gear.get_equipped, ALICE))["shield"]["durability"], 50)
        self.assertFalse(any("shield" in name for _, name in first["broken"]))
        second = await self.run_game(duel.fight, ALICE, BOB, 10)
        self.assertIn((ALICE, "iron shield (worn out: /repair it)"), second["broken"])
        shield = (await self.run_game(gear.get_equipped, ALICE))["shield"]
        self.assertEqual(shield["durability"], 0)  # still there, but unusable
        alice, _ = await self.run_game(duel.make_fighter, ALICE)
        self.assertEqual(alice.block_chance, 0.0)
        await self.run_game(duel.fight, ALICE, BOB, 10)
        self.assertEqual((await self.run_game(gear.get_equipped, ALICE))["shield"]["durability"], 0)
        cost = shop.repair_cost(shield)
        self.assertEqual(cost, round(6 * shop.ingot_value("iron") * 0.6))
        await self.run_game(shop.repair, ALICE, shield["gear_id"])
        self.assertEqual((await self.run_game(gear.get_equipped, ALICE))["shield"]["durability"], 100)

    async def test_a_tournament_match_uses_a_fight(self):
        await self.craft_shield()
        await self.run_game(tournament._fight, ALICE, BOB)
        self.assertEqual((await self.run_game(gear.get_equipped, ALICE))["shield"]["durability"], 50)

    async def test_the_dungeon_doesnt_use_it(self):
        from game import pve

        await self.craft_shield()
        settings.load({"pve": {"difficulties": {"easy": {"strength": 0.3}}}})
        await self.run_game(players.give_emeralds, ALICE, 100)
        run = await self.run_game(pve.create, ALICE, "easy")
        await self.run_game(pve.start, run["run_id"], ALICE)
        await self.run_game(pve.leave, run["run_id"], ALICE)
        self.assertEqual((await self.run_game(gear.get_equipped, ALICE))["shield"]["durability"], 100)

    async def test_no_unbreaking_on_a_shield(self):
        shield = await self.craft_shield()
        await self.run_game(enchants.give_book, ALICE, "unbreaking", 1)
        await self.run_game(enchants.give_lapis, ALICE, 10)
        with self.assertRaises(GameError):
            await self.run_game(enchants.apply, ALICE, "unbreaking:1", shield["gear_id"])
