"""Species: choosing one, and the bonus of each."""
from __future__ import annotations

import random

from game import (duel, enchants, gambling, gear, leaderboard, luckyblock, mining, players, roulette, settings,
                  shop, species, villager)
from game.errors import GameError
from tests.helpers import DAY, GameTestCase

ALICE, BOB = 1, 2


class ChoiceTests(GameTestCase):
    async def test_first_choice_free_then_paid_once_a_week(self):
        res = await self.run_game(species.choose, ALICE, "mage")
        self.assertEqual((res["before"], res["cost"]), (None, 0))
        with self.assertRaisesRegex(GameError, "already a"):
            await self.run_game(species.choose, ALICE, "mage")
        with self.assertRaisesRegex(GameError, "change your species again"):
            await self.run_game(species.choose, ALICE, "dwarf")
        self.advance(7 * DAY)
        with self.assertRaisesRegex(GameError, "Not enough"):
            await self.run_game(species.choose, ALICE, "dwarf")
        await self.run_game(players.give_emeralds, ALICE, 1500)
        res = await self.run_game(species.choose, ALICE, "dwarf")
        self.assertEqual((res["before"], res["cost"]), ("mage", 1000))
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 500)
        terms = await self.run_game(species.change_terms, ALICE)
        self.assertEqual((terms["current"], terms["ready"]), ("dwarf", False))

    async def test_staff_set_is_free_and_immediate(self):
        await self.run_game(species.choose, ALICE, "mage")
        res = await self.run_game(species.staff_set, ALICE, "witch")
        self.assertEqual((res["before"], res["species"]), ("mage", "witch"))
        await self.run_game(species.staff_set, ALICE, None)
        self.assertIsNone(await self.run_game(species.of, ALICE))
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 0)

    async def test_counts_and_display(self):
        await self.run_game(species.choose, ALICE, "miner")
        await self.run_game(players.give_emeralds, ALICE, 10)
        await self.run_game(players.give_emeralds, BOB, 20)
        self.assertEqual((await self.run_game(species.counts))["miner"], 1)
        data = await self.run_game(leaderboard.leaderboard, "emeralds", ALICE)
        self.assertEqual(data["species"], {ALICE: "⚒️"})
        self.assertIn("+10%", species.describe("mage"))


class BonusTests(GameTestCase):
    async def test_villager_sells_better(self):
        for uid in (ALICE, BOB):
            await self.run_game(players.add_blocks, uid, "obsidian", 10)
        await self.run_game(species.choose, ALICE, "villager")
        a = await self.run_game(players.sell_all_blocks, ALICE)
        b = await self.run_game(players.sell_all_blocks, BOB)
        self.assertEqual(a["base"], b["base"])
        self.assertEqual(a["bonus"] - b["bonus"], round(a["base"] * 0.05))

    async def test_villager_pays_less_at_the_market(self):
        for uid in (ALICE, BOB):
            await self.run_game(players.give_emeralds, uid, 10_000)
        await self.run_game(species.choose, ALICE, "villager")
        a = await self.run_game(shop.buy, ALICE, "diamond_ingot", 4)
        b = await self.run_game(shop.buy, BOB, "diamond_ingot", 4)
        self.assertEqual((a["price"], a["saved"], b["saved"]), (round(b["price"] * 0.95), b["price"] - a["price"], 0))

    async def test_villager_gets_better_villager_prices(self):
        await self.run_game(species.choose, ALICE, "villager")
        await self.run_game(players.give_emeralds, ALICE, 100_000)
        visit = await self.run_game(villager.arrive)
        offers = {o["kind"]: o for o in visit["offers"]}
        res = await self.run_game(villager.take, ALICE, visit["visit_id"], offers["sell"]["slot"])
        self.assertEqual(res["price"], round(offers["sell"]["price"] * 0.95))
        buy = offers["buy"]
        await self.run_game(players.add_blocks, ALICE, buy["asset"].split(":")[1], buy["amount"])
        res = await self.run_game(villager.take, ALICE, visit["visit_id"], buy["slot"])
        self.assertEqual(res["price"], round(buy["price"] * 1.05))

    async def test_dwarf_hits_harder_and_witch_drinks_better(self):
        await self.run_game(species.choose, ALICE, "dwarf")
        await self.run_game(species.choose, BOB, "witch")
        dwarf, _ = await self.run_game(duel.make_fighter, ALICE)
        witch, _ = await self.run_game(duel.make_fighter, BOB)
        self.assertAlmostEqual(dwarf.attack, witch.attack * 1.05)
        self.assertAlmostEqual(dwarf.min_attack, witch.min_attack * 1.05)
        self.assertEqual((dwarf.potion_boost, witch.potion_boost), (0.0, 0.10))
        settings.load({"duel": {"second_player_bonus_hp": 0}})
        witch.hp = dwarf.hp = 5
        fight = duel.Fight(random.Random(1), witch, dwarf)
        fight.index = 0  # the witch plays
        turn = fight.drink("healing")
        self.assertAlmostEqual(turn.healed, settings.get()["potions"]["healing_hp"] * 1.1)

    async def test_mage_enchantments_are_stronger(self):
        for uid in (ALICE, BOB):
            gid = await self.run_game(shop.create_gear, uid, "sword", "iron")
            await self.run_game(lambda ctx, g=gid: enchants.set_enchants(ctx, g, {"sharpness": 3}))
            await self.run_game(gear.equip, uid, gid)
        await self.run_game(species.choose, ALICE, "mage")
        mage = await self.run_game(gear.get_equipped, ALICE)
        other = await self.run_game(gear.get_equipped, BOB)
        sharp = settings.get()["enchants"]["sharpness_damage"][2]
        self.assertAlmostEqual(gear.attack_damage(mage) - gear.attack_damage(other), sharp * 0.10)
        self.assertEqual(mage["sword"]["enchant_boost"], 1.1)

    async def test_miner_mines_faster(self):
        await self.run_game(species.choose, ALICE, "miner")
        a = await self.run_game(mining.mine, ALICE)
        b = await self.run_game(mining.mine, BOB)
        self.assertEqual(a["cooldown"], round(b["cooldown"] * 0.95))
        self.assertLess(a["cooldown"], b["cooldown"])

    async def test_gambler_bets_more(self):
        await self.run_game(species.choose, ALICE, "gambler")
        for user in (ALICE, BOB):
            await self.run_game(players.give_emeralds, user, 5000)
        self.assertEqual(await self.run_game(gambling.max_bet, ALICE), 300)
        self.assertEqual(await self.run_game(gambling.max_bet, BOB), 200)
        await self.run_game(luckyblock.open_block, ALICE, 300)
        await self.run_game(roulette.spin, ALICE, "red", 300)
        with self.assertRaisesRegex(GameError, "300"):
            await self.run_game(roulette.spin, ALICE, "red", 301)
        with self.assertRaisesRegex(GameError, "200"):
            await self.run_game(luckyblock.open_block, BOB, 300)
        with self.assertRaisesRegex(GameError, "200"):
            await self.run_game(roulette.spin, BOB, "red", 201)

    async def test_no_species_no_bonus(self):
        for key in species.SPECIES:
            self.assertEqual(await self.run_game(species.bonus, ALICE, key), 0.0)
