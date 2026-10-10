"""/reset: one player or everyone, part by part, without touching the rest."""
from __future__ import annotations

from game import assets, enchants, exchange, links, players, reset, seasons, shop
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2


class ResetTests(GameTestCase):
    overrides = {"achievements": {"first_craft": {"reward": 0}}}

    async def fill(self, user_id: int) -> None:
        await self.run_game(players.give_emeralds, user_id, 500)
        await self.run_game(players.add_blocks, user_id, "bedrock", 10)
        await self.run_game(enchants.give_lapis, user_id, 5)
        gear_id = await self.run_game(shop.create_gear, user_id, "sword", "iron")
        await self.run_game(enchants.set_enchants, gear_id, {"sharpness": 2})
        await self.run_game(players.set_level, user_id, 30)
        await self.run_game(players.add_score, user_id, 100)
        await self.run_game(players.bump_stat, user_id, "blocks_mined", 1000)

    async def snapshot(self, user_id: int) -> dict:
        def run(ctx):
            user = players.get_user(ctx, user_id)
            return {
                "emeralds": user["emeralds"], "level": user["level"], "owned": dict(assets.owned(ctx, user_id)),
                "stats": players.get_stats(ctx, user_id),
                "achievements": ctx.one("SELECT COUNT(*) AS n FROM achievements WHERE user_id=?;", (user_id,))["n"],
            }
        return await self.run_game(run)

    async def test_one_player_everything(self):
        await self.fill(ALICE)
        await self.fill(BOB)
        await self.run_game(exchange.list_for_sale, ALICE, "block:bedrock", 5, 50)
        bob_before = await self.snapshot(BOB)
        result = await self.run_game(reset.apply, list(reset.PARTS), ALICE)
        self.assertEqual(result["players"], 1)
        alice = await self.snapshot(ALICE)
        self.assertEqual((alice["emeralds"], alice["level"], alice["owned"], alice["stats"], alice["achievements"]),
                         (0, 1, {}, {}, 0))
        self.assertEqual(await self.snapshot(BOB), bob_before)  # nobody else is touched
        self.assertEqual(await self.run_game(lambda ctx: ctx.one("SELECT COUNT(*) AS n FROM gear_enchants;")["n"]), 1)
        self.assertEqual((await self.run_game(exchange.browse))["total"], 0)  # Alice's listing is gone

    async def test_only_some_parts(self):
        await self.fill(ALICE)
        before = await self.snapshot(ALICE)
        await self.run_game(reset.apply, ["gear"], ALICE)
        alice = await self.snapshot(ALICE)
        self.assertEqual(alice["emeralds"], before["emeralds"])
        self.assertNotIn("gear:iron:sword:sharpness2", alice["owned"])
        self.assertIn("block:bedrock", alice["owned"])
        await self.run_game(reset.apply, ["levels"], ALICE)
        user = await self.run_game(players.get_user, ALICE)
        self.assertEqual((user["level"], user["xp"], user["talent_points"]), (1, 0, 0))

    async def test_everyone_keeps_links_and_paid_seasons(self):
        await self.fill(ALICE)
        await self.fill(BOB)
        await self.run_game(links.request_link, ALICE, "Steve")
        self.advance(8 * 86400)
        await self.run_game(seasons.close_finished)
        closed = await self.run_game(lambda ctx: ctx.one("SELECT COUNT(*) AS n FROM seasons_closed;")["n"])
        result = await self.run_game(reset.apply, list(reset.PARTS))
        self.assertEqual(result["players"], 2)
        for uid in (ALICE, BOB):
            self.assertEqual((await self.snapshot(uid))["emeralds"], 0)
        self.assertEqual(await self.run_game(lambda ctx: ctx.one("SELECT COUNT(*) AS n FROM seasons_closed;")["n"]), closed)
        self.assertEqual(await self.run_game(lambda ctx: ctx.one("SELECT COUNT(*) AS n FROM season_results;")["n"]), 0)
        self.assertIsNotNone(await self.run_game(links.get_link, ALICE))

    async def test_unknown_part(self):
        with self.assertRaises(ValueError):
            await self.run_game(reset.apply, ["everything"])
