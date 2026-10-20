"""Biomes of the week (2.0.6): the draw, the effects and the biome's challenge."""
from __future__ import annotations

import random

from game import biomes, duel, gambling, mining, players, progress, robbery, shop
from game.notices import ChallengeCompleted
from tests.helpers import DAY, GameTestCase

ALICE, BOB = 1, 2


class BiomeTestCase(GameTestCase):
    biomes_on = True

    async def set_biome(self, key: str) -> None:
        await self.run_game(biomes.force, key)


class DrawTests(BiomeTestCase):
    async def test_kept_for_the_week_and_never_twice_in_a_row(self):
        seen = []
        for _ in range(12):
            first = (await self.run_game(biomes.current)).key
            self.assertEqual((await self.run_game(biomes.current)).key, first)  # the same all week
            seen.append(first)
            self.advance(7 * DAY)
        self.assertTrue(all(a != b for a, b in zip(seen, seen[1:])), seen)
        self.assertGreater(len(set(seen)), 3)

    async def test_only_enabled_ones_are_drawn(self):
        from game import settings

        settings.load({"biomes": {"enabled": {k: k == "ocean" for k in biomes.BIOMES}}})
        for _ in range(3):
            self.assertEqual((await self.run_game(biomes.current)).key, "ocean")  # alone: again and again
            self.advance(7 * DAY)
        settings.load({"biomes": {"enabled": {k: False for k in biomes.BIOMES}}})
        self.assertIsNone(await self.run_game(biomes.current))
        self.assertEqual(await self.run_game(biomes.multiplier, "sell"), 1.0)

    async def test_announced_once_a_week(self):
        await self.set_biome("tundra")
        self.assertEqual((await self.run_game(biomes.to_announce)).key, "tundra")
        self.assertIsNone(await self.run_game(biomes.to_announce))
        self.advance(7 * DAY)
        self.assertIsNotNone(await self.run_game(biomes.to_announce))

    def test_factors(self):
        self.assertAlmostEqual(biomes.factor("sell", True), 1.15)
        self.assertAlmostEqual(biomes.factor("sell", False), 0.90)
        self.assertAlmostEqual(biomes.factor("cooldown", True), 0.85)
        self.assertAlmostEqual(biomes.factor("cooldown", False), 1.10)
        self.assertAlmostEqual(biomes.factor("drops", True), 1.5)
        self.assertAlmostEqual(biomes.factor("drops", False), 0.9)
        self.assertEqual(biomes.describe("market", True), "/market prices -15%")
        self.assertEqual(biomes.describe("rare_odds", True), "rare blocks when mining ×1.5")
        for b in biomes.BIOMES.values():  # every biome's effects and challenge exist
            self.assertIn(b.bonus, biomes.EFFECTS)
            self.assertIn(b.malus, biomes.EFFECTS)
            self.assertIn(b.challenge, progress.CHALLENGE_CODES)


class EffectTests(BiomeTestCase):
    async def sell(self) -> dict:
        await self.run_game(players.add_blocks, ALICE, "cobblestone", 1000)
        return await self.run_game(players.sell_blocks, ALICE)

    async def test_sell_bonus_and_malus(self):
        await self.set_biome("mountains")
        self.assertEqual((await self.sell())["bonus"], 150)
        await self.set_biome("badlands")
        before = await self.run_game(players.get_emeralds, ALICE)
        res = await self.sell()
        self.assertEqual(res["bonus"], -100)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), before + 900)

    async def test_mining_cooldown(self):
        await self.set_biome("forest")
        normal = (await self.run_game(mining.mine, ALICE))["cooldown"]
        await self.set_biome("tundra")
        self.assertEqual((await self.run_game(mining.mine, ALICE))["cooldown"], round(normal * 0.85))
        await self.set_biome("ocean")
        res = await self.run_game(mining.mine, ALICE)
        self.assertEqual((res["cooldown"], res["drop_chance"]), (round(normal * 1.10), 1.5))

    async def test_market_prices(self):
        await self.run_game(players.give_emeralds, ALICE, 100_000)
        key = next(iter(shop.market_offers()))
        price = shop.market_offers()[key]["price"]
        await self.set_biome("forest")
        self.assertEqual((await self.run_game(shop.buy, ALICE, key, 100))["price"], round(100 * price * 0.85))
        await self.set_biome("mushroom")
        self.assertEqual((await self.run_game(shop.buy, ALICE, key, 100))["price"], round(100 * price * 1.10))

    async def test_highest_bet(self):
        normal = await self.run_game(gambling.max_bet)
        await self.set_biome("desert")
        self.assertEqual(await self.run_game(gambling.max_bet), round(normal * 1.5))

    async def test_potions_and_rob_loot(self):
        await self.set_biome("swamp")
        fighter, _ = await self.run_game(duel.make_fighter, ALICE)
        self.assertAlmostEqual(fighter.potion_boost, 0.15)
        await self.set_biome("dark_forest")
        await self.run_game(players.give_emeralds, BOB, 10_000)
        await self.run_game(players.set_level, BOB, 10)
        settings_rob = __import__("game.settings", fromlist=["get"]).get()["rob"]
        rob = await self.run_game(robbery.start, ALICE, BOB, "discreet")
        self.assertLessEqual(rob["amount"], round(int(settings_rob["discreet_max"]) * 1.15))
        self.assertGreaterEqual(rob["amount"], round(int(settings_rob["discreet_min"]) * 1.15))


class ChallengeTests(BiomeTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.run_game(players.ensure_user, ALICE)

    async def test_the_biome_challenge_pays_apart(self):
        await self.set_biome("tundra")
        c = await self.run_game(progress.biome_challenge)
        self.assertEqual((c.stat, c.target, c.reward), ("blocks_mined", 900, 250))
        await self.run_game(progress.on_stat, ALICE, "blocks_mined", 899)
        self.assertFalse((await self.run_game(progress.biome_progress, ALICE))["completed"])
        before = await self.run_game(players.get_emeralds, ALICE)
        await self.run_game(progress.on_stat, ALICE, "blocks_mined", 5)
        p = await self.run_game(progress.biome_progress, ALICE)
        self.assertEqual((p["progress"], p["completed"]), (900, True))
        self.assertGreaterEqual(await self.run_game(players.get_emeralds, ALICE), before + 250)
        self.assertTrue(any(isinstance(n, ChallengeCompleted) and n.text.startswith("❄️ Tundra") for n in self.notices))
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "biome_challenges"), 1)
        await self.run_game(progress.on_stat, ALICE, "blocks_mined", 500)  # paid once
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "biome_challenges"), 1)

    async def test_one_biome_challenge_paid_a_week(self):
        await self.set_biome("tundra")
        await self.run_game(progress.on_stat, ALICE, "blocks_mined", 900)
        await self.set_biome("forest")  # the staff changed it after Alice finished hers
        await self.run_game(progress.on_stat, ALICE, "items_crafted", 5)
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "biome_challenges"), 1)
        self.assertTrue((await self.run_game(progress.biome_progress, ALICE))["completed"])

    async def test_progress_belongs_to_its_biome(self):
        await self.set_biome("tundra")
        await self.run_game(progress.on_stat, ALICE, "blocks_mined", 500)
        await self.set_biome("forest")  # the staff changed it: a new challenge
        self.assertEqual((await self.run_game(progress.biome_progress, ALICE))["progress"], 0)
