"""2.2.2: the enchanting table, Fire Aspect, Thorns, Sweeping Edge and the curses."""
from __future__ import annotations

import json
import random
import unittest

from game import (assets, duel, enchanting_table, enchants, exchange, gate, gear, players, pve, raid_fight,
                  settings, shop)
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2


class TableTests(GameTestCase):
    async def _materials(self, uid=ALICE):
        await self.run_game(players.add_blocks, uid, "obsidian", 4)
        await self.run_game(players.add_item, uid, "ingot", "diamond", 2)
        await self.run_game(enchants.give_book, uid, "sharpness", 3)
        await self.run_game(enchants.give_book, uid, "fortune", 1)  # the cheapest: it goes

    async def test_craft_uses_the_cheapest_book_once(self):
        with self.assertRaisesRegex(GameError, "missing"):
            await self.run_game(shop.craft, ALICE, "enchanting_table")
        await self._materials()
        res = await self.run_game(shop.craft, ALICE, "enchanting_table")
        self.assertEqual(res["books"], [("fortune", 1)])
        self.assertTrue(await self.run_game(enchanting_table.has, ALICE))
        self.assertEqual((await self.run_game(players.get_blocks, ALICE))["obsidian"], 0)
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "diamond"), 0)
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "book", "sharpness:3"), 1)
        await self._materials()
        with self.assertRaisesRegex(GameError, "already"):
            await self.run_game(shop.craft, ALICE, "enchanting_table")

    async def test_enchant_a_blank_piece_for_lapis(self):
        sword = await self.run_game(shop.create_gear, ALICE, "sword", "diamond")
        with self.assertRaisesRegex(GameError, "enchanting table"):
            await self.run_game(enchanting_table.enchant, ALICE, sword)
        await self._materials()
        await self.run_game(shop.craft, ALICE, "enchanting_table")
        with self.assertRaisesRegex(GameError, "lapis"):
            await self.run_game(enchanting_table.enchant, ALICE, sword)
        await self.run_game(enchants.give_lapis, ALICE, 13)
        res = await self.run_game(enchanting_table.enchant, ALICE, sword)
        self.assertEqual(await self.run_game(enchants.lapis, ALICE), 1)
        good = {k: v for k, v in res["enchants"].items() if not enchants.ENCHANTS[k].curse}
        self.assertTrue(1 <= len(good) <= 3)
        for name, level in good.items():
            self.assertIn("sword", enchants.ENCHANTS[name].items)
            self.assertNotEqual(name, "mending")
            self.assertLessEqual(level, 3)  # the overworld's maximum
        with self.assertRaisesRegex(GameError, "without any enchantment"):  # once only
            await self.run_game(enchanting_table.enchant, ALICE, sword)

    async def test_no_shield(self):
        shield = await self.run_game(shop.create_gear, ALICE, "shield", "iron")
        with self.assertRaisesRegex(GameError, "can't enchant"):
            await self.run_game(enchanting_table.enchant, ALICE, shield)


class DrawTests(unittest.TestCase):
    def setUp(self):
        settings.load()

    def test_the_top_level_is_very_rare(self):
        self.assertEqual(enchanting_table.level_weights(3), [60.0, 30.0, 1.0])
        self.assertEqual(enchanting_table.level_weights(5), [60.0, 30.0, 9.0, 4.0, 1.0])
        rng = random.Random(1)
        draws = [enchanting_table.draw(rng, "chestplate", 3) for _ in range(20000)]
        levels = [lvl for d in draws for k, lvl in d.items() if not enchants.ENCHANTS[k].curse]
        self.assertAlmostEqual(levels.count(3) / len(levels), 1 / 91, delta=0.004)
        counts = [len([k for k in d if not enchants.ENCHANTS[k].curse]) for d in draws]
        self.assertAlmostEqual(counts.count(1) / len(counts), 0.6, delta=0.02)
        self.assertAlmostEqual(counts.count(3) / len(counts), 0.1, delta=0.01)
        cursed = sum(1 for d in draws if any(enchants.ENCHANTS[k].curse for k in d))
        self.assertAlmostEqual(cursed / len(draws), 0.10, delta=0.01)

    def test_a_shovel_gets_two_at_most(self):
        rng = random.Random(2)
        for _ in range(500):
            d = enchanting_table.draw(rng, "shovel", 7)
            self.assertLessEqual(len([k for k in d if not enchants.ENCHANTS[k].curse]), 2)

    def test_curses_never_come_as_books(self):
        self.assertNotIn("binding", enchants.RANDOM_BOOKS)
        with self.assertRaises(GameError):
            enchants.parse_book("vanishing:1")
        self.assertFalse(any(k.startswith(("book:binding", "book:vanishing")) for k in assets.catalog()))
        self.assertEqual(enchants.parse_signature("fire_aspect2,binding1"), {"fire_aspect": 2, "binding": 1})


class CurseTests(GameTestCase):
    async def _bound(self, uid=ALICE, curse="binding"):
        piece = await self.run_game(shop.create_gear, uid, "chestplate", "iron")
        await self.run_game(enchants.set_enchants, piece, {"protection": 1, curse: 1})
        await self.run_game(gear.equip, uid, piece)
        return piece

    async def test_binding_keeps_the_piece_on(self):
        piece = await self._bound()
        other = await self.run_game(shop.create_gear, ALICE, "chestplate", "diamond")
        for fn, args in ((gear.unequip, ("chestplate",)), (gear.equip, (other,)), (shop.sell_gear, (piece,))):
            with self.assertRaisesRegex(GameError, "Binding"):
                await self.run_game(fn, ALICE, *args)
        key = "gear:iron:chestplate:binding1,protection1"
        with self.assertRaisesRegex(GameError, "Binding"):
            await self.run_game(exchange.list_for_sale, ALICE, key, 1, 100)
        self.assertEqual(await self.run_game(gear.unequip_all, ALICE), [])
        self.assertEqual((await self.run_game(assets.staff_take, ALICE, key, 1))[0], 1)  # the staff still can

    async def test_vanishing_on_a_fall(self):
        piece = await self._bound(curse="vanishing")
        sword = await self.run_game(shop.create_gear, ALICE, "sword", "iron")
        pieces = await self.run_game(gear.get_pieces, {"chestplate": piece, "sword": sword})
        gone = await self.run_game(gear.vanish, pieces)
        self.assertEqual([p["gear_id"] for p in gone], [piece])
        left = [g["gear_id"] for g in await self.run_game(shop.get_gear, ALICE)]
        self.assertEqual(left, [sword])


class CombatTests(unittest.TestCase):
    def setUp(self):
        settings.load()

    def test_fire_burns_through_armor_in_a_duel(self):
        a = duel.Fighter(ALICE, attack=5, reduction=0.0, hp=100, min_attack=5, fire=1.5)
        b = duel.Fighter(BOB, attack=1, reduction=0.9, hp=100, min_attack=1)
        fight = duel.Fight(random.Random(1), a, b)
        fight.index = 0
        fight.play(random.Random(1))
        self.assertEqual(b.burning, 3)
        hp = b.hp
        turn = fight.play(random.Random(1))  # Bob's turn: he burns first
        self.assertEqual(turn.burn, 1.5)
        self.assertLess(b.hp, hp)
        self.assertEqual(b.burning, 2)

    def test_thorns_hit_back_and_can_win(self):
        a = duel.Fighter(ALICE, attack=10, reduction=0.0, hp=1, min_attack=10)
        b = duel.Fighter(BOB, attack=1, reduction=0.0, hp=100, min_attack=1, thorns=0.5)
        fight = duel.Fight(random.Random(3), a, b)
        fight.index = 0
        turn = fight.play(random.Random(3))
        self.assertGreater(turn.thorns, 0)
        self.assertIs(fight.winner, b)

    def test_old_saved_fights_still_load(self):
        f = gate.new_fight("wither", [gate.Player(ALICE, 10, 1, 0.2, 20)])
        data = json.loads(f.to_json())
        for key in ("burning", "burn", "burner"):
            data.pop(key)
        for p in data["players"]:
            p.pop("fire"), p.pop("thorns")
        loaded = gate.Fight.from_json(json.dumps(data))
        self.assertEqual(loaded.burning, 0)
        r = raid_fight.RaidFight([raid_fight.Fighter(ALICE, "attack", 10, 1, 0.2, 20)])
        data = json.loads(r.to_json())
        for x in data["fighters"]:
            for key in ("fire", "thorns", "burning", "burn_damage", "burner"):
                x.pop(key)
        self.assertEqual(raid_fight.RaidFight.from_json(json.dumps(data)).fighters[0].burning, 0)

    def test_the_boss_burns_on_its_turn(self):
        p = gate.Player(ALICE, 10, 10, 0.9, 1000, fire=2.0)
        f = gate.new_fight("wither", [p])
        f.attack(random.Random(1), ALICE)  # Alice hits, then the boss burns before striking
        self.assertTrue(any("burns" in line for line in f.log))
        self.assertEqual(f.burner, ALICE)

    def test_sweeping_edge_hits_a_second_monster(self):
        rng = random.Random(4)
        hero = pve.Hero(ALICE, 1.0, 1.0, 0.99, 1000, 1000, sweep=1.0)
        monsters = [pve.Monster("zombie", 100, (0.1, 0.1)), pve.Monster("zombie", 100, (0.1, 0.1))]
        pve.fight_wave(rng, [hero], 1, "normal", monsters)
        self.assertTrue(all(m.hp < 100 for m in monsters))

    def test_thorns_in_the_dungeon(self):
        hero = pve.Hero(ALICE, 0.0, 0.0, 0.0, 1000, 1000, thorns=1.0)
        monster = pve.Monster("zombie", 3, (2.0, 2.0))
        pve.fight_wave(random.Random(5), [hero], 1, "normal", [monster])
        self.assertLessEqual(monster.hp, 0)


if __name__ == "__main__":
    unittest.main()
