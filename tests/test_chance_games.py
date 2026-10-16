"""Blackjack and mines: games of chance played over several clicks."""
from __future__ import annotations

import random

from game import blackjack, gambling, mines, players, settings
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2
MINUTE = 60


def set_hand(ctx, game_id: int, player: list[str], dealer: list[str]) -> None:
    game = gambling.get_game(ctx, game_id)
    game["state"].update({"player": player, "dealer": dealer})
    gambling.save_game(ctx, game)


class BlackjackTests(GameTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.run_game(players.give_emeralds, ALICE, 1000)

    def test_values(self):
        self.assertEqual(blackjack.value(["A♠", "K♥"]), 21)
        self.assertEqual(blackjack.value(["A♠", "A♥", "9♦"]), 21)
        self.assertEqual(blackjack.value(["K♠", "Q♥", "5♦"]), 25)
        self.assertTrue(blackjack.is_blackjack(["A♠", "10♣"]))
        self.assertFalse(blackjack.is_blackjack(["7♠", "7♣", "7♦"]))

    async def start(self, player, dealer, amount=100):
        settings.load({"games": {"blackjack_dealer_stands": 17}})
        for seed in range(500):  # a deal without a blackjack, then the cards we want
            self.db.rng = random.Random(seed)
            game = await self.run_game(blackjack.start, ALICE, amount)
            if game["status"] == "active":
                await self.run_game(set_hand, game["game_id"], player, dealer)
                return game
            await self.run_game(players.give_emeralds, ALICE, amount * 3)  # keep enough to play again
        raise AssertionError("no plain deal found")

    async def test_stand_and_win(self):
        game = await self.start(["10♠", "9♥"], ["10♦", "7♣"])
        res = await self.run_game(blackjack.stand, game["game_id"], ALICE)
        self.assertEqual((res["result"], res["paid"], res["status"]), ("win", 200, "done"))
        with self.assertRaisesRegex(GameError, "over"):
            await self.run_game(blackjack.hit, game["game_id"], ALICE)

    async def test_bust_and_push(self):
        game = await self.start(["10♠", "6♥"], ["10♦", "7♣"])
        self.db.rng = random.Random(0)
        while True:
            res = await self.run_game(blackjack.hit, game["game_id"], ALICE)
            if res["status"] == "done":
                break
        self.assertIn(res["result"], ("bust", "win", "lose", "push"))
        if blackjack.value(res["state"]["player"]) > 21:
            self.assertEqual((res["result"], res["paid"]), ("bust", 0))
        game = await self.start(["10♠", "7♥"], ["10♦", "7♣"])
        res = await self.run_game(blackjack.stand, game["game_id"], ALICE)
        self.assertEqual((res["result"], res["paid"]), ("push", 100))

    async def test_double(self):
        game = await self.start(["5♠", "6♥"], ["10♦", "7♣"])
        before = await self.run_game(players.get_emeralds, ALICE)
        res = await self.run_game(blackjack.double, game["game_id"], ALICE)
        self.assertEqual((res["bet"], len(res["state"]["player"]), res["status"]), (200, 3, "done"))
        after = await self.run_game(players.get_emeralds, ALICE)
        self.assertEqual(after - before, res["paid"] - 100)  # the second 100 was taken, then the hand paid

    async def test_a_natural_pays_three_to_two(self):
        game = await self.start(["A♠", "K♥"], ["10♦", "7♣"])
        res = await self.run_game(blackjack.stand, game["game_id"], ALICE)
        self.assertEqual((res["result"], res["paid"]), ("blackjack", 250))

    async def test_only_the_player_and_one_hand_at_a_time(self):
        game = await self.start(["10♠", "2♥"], ["10♦", "7♣"])
        with self.assertRaisesRegex(GameError, "isn't your game"):
            await self.run_game(blackjack.stand, game["game_id"], BOB)
        with self.assertRaisesRegex(GameError, "already have a game"):
            await self.run_game(blackjack.start, ALICE, 10)

    async def test_no_move_means_stand(self):
        game = await self.start(["10♠", "9♥"], ["10♦", "7♣"])
        self.advance(4 * MINUTE)
        done = await self.run_game(blackjack.expire)
        self.assertEqual([(g["game_id"], g["result"]) for g in done], [(game["game_id"], "win")])


class MinesTests(GameTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.run_game(players.give_emeralds, ALICE, 1000)

    def test_multipliers(self):
        self.assertAlmostEqual(mines.multiplier(1, 3), 0.95 * 20 / 17)
        self.assertAlmostEqual(mines.multiplier(2, 3), 0.95 * 20 / 17 * 19 / 16)
        self.assertEqual(mines.multiplier(0, 3), 0.0)
        self.assertEqual(mines.multiplier(10, 10), 25.0)  # capped

    async def test_dig_and_cash_out(self):
        game = await self.run_game(mines.start, ALICE, 100, 3)
        safe = [c for c in range(mines.CELLS) if c not in game["state"]["tnt"]]
        with self.assertRaisesRegex(GameError, "at least one"):
            await self.run_game(mines.cash_out, game["game_id"], ALICE)
        await self.run_game(mines.dig, game["game_id"], ALICE, safe[0])
        await self.run_game(mines.dig, game["game_id"], ALICE, safe[1])
        with self.assertRaisesRegex(GameError, "haven't dug"):
            await self.run_game(mines.dig, game["game_id"], ALICE, safe[1])
        res = await self.run_game(mines.cash_out, game["game_id"], ALICE)
        self.assertEqual((res["result"], res["paid"]), ("cashed", round(100 * mines.multiplier(2, 3))))
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 1000 - 100 + res["paid"])

    async def test_the_tnt(self):
        game = await self.run_game(mines.start, ALICE, 100, 5)
        res = await self.run_game(mines.dig, game["game_id"], ALICE, game["state"]["tnt"][0])
        self.assertEqual((res["result"], res["paid"], res["state"]["boom"]), ("boom", 0, game["state"]["tnt"][0]))
        self.assertEqual(await self.run_game(gambling.net_today, ALICE), -100)

    async def test_limits(self):
        with self.assertRaisesRegex(GameError, "1 to 10"):
            await self.run_game(mines.start, ALICE, 100, 11)
        with self.assertRaisesRegex(GameError, "Bets go"):
            await self.run_game(mines.start, ALICE, 5000, 3)

    async def test_no_move(self):
        game = await self.run_game(mines.start, ALICE, 100, 3)
        self.advance(4 * MINUTE)
        res = (await self.run_game(mines.expire))[0]
        self.assertEqual((res["result"], res["paid"]), ("refunded", 100))  # nothing dug: the bet back
        self.assertEqual(await self.run_game(gambling.net_today, ALICE), 0)
        game = await self.run_game(mines.start, ALICE, 100, 3)
        safe = next(c for c in range(mines.CELLS) if c not in game["state"]["tnt"])
        await self.run_game(mines.dig, game["game_id"], ALICE, safe)
        self.advance(4 * MINUTE)
        self.assertEqual((await self.run_game(mines.expire))[0]["result"], "cashed")
