from __future__ import annotations

import random
import unittest

from game import assets, duel, events, exchange, leaderboard, players, potions, settings
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB, CAROL, DAVE = 1, 2, 3, 4


def fighters(attack: float = 10, reduction: float = 0.0) -> tuple[duel.Fighter, duel.Fighter]:
    return duel.Fighter(ALICE, attack, reduction, 20), duel.Fighter(BOB, attack, reduction, 20)


class FightEngineTests(unittest.TestCase):
    def setUp(self):
        # Exact numbers: no crits, no dodges, no bonus HP for the second player.
        settings.load({"duel": {"crit_chance": 0, "dodge_chance": 0, "second_player_bonus_hp": 0}})

    def test_turns_alternate(self):
        fight = duel.Fight(random.Random(1), *fighters(attack=1))
        first = fight.current.user_id
        fight.play(random.Random(2))
        self.assertNotEqual(fight.current.user_id, first)
        self.assertEqual(fight.rounds, 1)

    def test_strength_boosts_this_attack(self):
        plain = duel.Fight(random.Random(5), *fighters())
        strong = duel.Fight(random.Random(5), *fighters())
        normal_hit = plain.play(random.Random(7)).hits[0].damage
        boosted = strong.play(random.Random(7), "strength")
        # Same roll r: 1 + 9r without the potion, (1 + 5) + 4r with it (the maximum stays 10).
        r = (normal_hit - 1) / 9
        self.assertAlmostEqual(boosted.hits[0].damage, 6 + 4 * r)
        self.assertEqual(strong.fighter(boosted.attacker).potions_used, 1)

    def test_healing_never_goes_over_max_hp(self):
        fight = duel.Fight(random.Random(1), *fighters(attack=1))
        fight.current.hp = 10
        self.assertEqual(fight.play(random.Random(1), "healing").healed, 3)
        fight.play(random.Random(1))
        fight.current.hp = 19
        self.assertEqual(fight.play(random.Random(1), "healing").healed, 1)

    def test_harming_is_reduced_by_armor(self):
        fight = duel.Fight(random.Random(1), *fighters(attack=1, reduction=0.3))
        defender = fight.other
        turn = fight.play(random.Random(1), "harming")
        self.assertAlmostEqual(turn.direct, 2.1)  # 3 x (1 - 0.3)
        self.assertAlmostEqual(defender.hp, 20 - 2.1 - turn.hits[0].damage)

    def test_speed_lasts_three_turns(self):
        settings.load({"duel": {"crit_chance": 0}, "potions": {"speed_chance": 1}})
        fight = duel.Fight(random.Random(1), *fighters(attack=0.1))
        me = fight.current.user_id
        hits = []
        for i in range(8):
            turn = fight.play(random.Random(i), "speed" if i == 0 else None)
            if turn.attacker == me:
                hits.append(len(turn.hits))
        self.assertEqual(hits, [2, 2, 2, 1])

    def test_three_potions_per_duel(self):
        fight = duel.Fight(random.Random(1), *fighters(attack=0.1))
        me = fight.current
        for i in range(3):
            fight.play(random.Random(i), "healing")
            fight.play(random.Random(i))
        self.assertEqual(fight.current, me)
        with self.assertRaisesRegex(GameError, "already drank"):
            fight.play(random.Random(9), "healing")

    def test_drink_then_attack_in_the_same_turn(self):
        plain = duel.Fight(random.Random(5), *fighters())
        strong = duel.Fight(random.Random(5), *fighters())
        normal_hit = plain.play(random.Random(7)).hits[0].damage
        me = strong.current.user_id
        drunk = strong.drink("strength")
        self.assertEqual((drunk.potion, drunk.hits), ("strength", []))
        self.assertEqual(strong.current.user_id, me)  # still my turn
        self.assertFalse(strong.can_drink)
        with self.assertRaisesRegex(GameError, "already drank a potion this turn"):
            strong.drink("healing")
        turn = strong.play(random.Random(7))
        self.assertIs(turn, drunk)
        self.assertAlmostEqual(turn.hits[0].damage, 6 + 4 * (normal_hit - 1) / 9)
        self.assertNotEqual(strong.current.user_id, me)
        self.assertTrue(strong.can_drink)

    def test_healing_shows_before_the_attack(self):
        fight = duel.Fight(random.Random(1), *fighters(attack=1))
        fight.current.hp = 10
        self.assertEqual(fight.drink("healing").healed, 3)
        self.assertEqual(fight.current.hp, 13)

    def test_harming_can_finish_the_opponent(self):
        fight = duel.Fight(random.Random(1), *fighters(attack=1))
        fight.other.hp = 3
        fight.drink("harming")
        self.assertEqual(fight.other.hp, 0)
        turn = fight.play(random.Random(1))
        self.assertEqual(turn.hits, [])
        self.assertTrue(fight.over)

    def test_damage_is_between_min_and_max(self):
        fight = duel.Fight(random.Random(1), *fighters(attack=10))
        for i in range(30):
            fight.current.hp = fight.other.hp = 1000  # keep the fight going
            hit = fight.play(random.Random(i)).hits[0]
            self.assertTrue(1 <= hit.damage <= 10, hit.damage)

    def test_dodges(self):
        settings.load({"duel": {"dodge_chance": 1, "second_player_bonus_hp": 0}})
        fight = duel.Fight(random.Random(1), *fighters())
        turn = fight.play(random.Random(1))
        self.assertTrue(turn.hits[0].dodged)
        self.assertEqual(fight.current.hp, 20)

    def test_second_player_starts_with_bonus_hp(self):
        settings.load({"duel": {"second_player_bonus_hp": 2}})
        fight = duel.Fight(random.Random(1), *fighters())
        self.assertEqual((fight.current.hp, fight.other.hp, fight.other.max_hp), (20, 22, 22))

    def test_one_reinforced_potion_per_duel(self):
        fight = duel.Fight(random.Random(1), *fighters(attack=0.1))
        fight.play(random.Random(1), "healing:2")
        fight.play(random.Random(2))
        with self.assertRaisesRegex(GameError, "one reinforced"):
            fight.drink("strength:2")
        fight.drink("strength")  # level I is fine

    def test_better_gear_wins_more_often_not_always(self):
        settings.load()
        wins = 0
        rng = random.Random(4)
        for _ in range(3000):
            strong = duel.Fighter(ALICE, 14, 0.288, 20)  # netherite
            weak = duel.Fighter(BOB, 10, 0.18, 20)  # iron
            wins += duel.simulate(rng, strong, weak).winner == 0
        self.assertTrue(0.65 < wins / 3000 < 0.92, wins / 3000)

    def test_a_fight_always_ends(self):
        fight = duel.Fight(random.Random(3), *fighters(attack=1, reduction=0.8))
        fight.auto_play(random.Random(3))
        self.assertTrue(fight.over)
        self.assertLessEqual(fight.rounds, settings.get()["duel"]["max_rounds"])


class DuelFlowTests(GameTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.run_game(players.give_emeralds, ALICE, 100)
        await self.run_game(players.give_emeralds, BOB, 100)

    async def test_stakes_are_held_then_paid(self):
        setup = await self.run_game(duel.start, ALICE, BOB, 40)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 60)
        fight = setup["fight"]
        fight.auto_play(random.Random(1))
        res = await self.run_game(duel.finish, setup["duel_id"], fight)
        self.assertEqual(await self.run_game(players.get_emeralds, res["loser"]), 60)
        with self.assertRaisesRegex(GameError, "not running"):
            await self.run_game(duel.finish, setup["duel_id"], fight)

    async def test_interrupted_duels_are_refunded(self):
        await self.run_game(duel.start, ALICE, BOB, 40)
        refunded = await self.run_game(duel.refund_interrupted)
        self.assertEqual(len(refunded), 1)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 100)
        self.assertEqual(await self.run_game(players.get_emeralds, BOB), 100)

    async def test_start_lists_the_potions(self):
        await self.run_game(potions.give, ALICE, "strength", 2)
        setup = await self.run_game(duel.start, ALICE, BOB, 10)
        self.assertEqual(setup["potions"], {ALICE: {"strength": 2}, BOB: {}})

    async def test_drinking_uses_the_potion(self):
        await self.run_game(potions.give, ALICE, "healing")
        await self.run_game(potions.drink, ALICE, "healing")
        self.assertEqual(await self.run_game(potions.owned, ALICE), {})
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "potions_drunk"), 1)
        with self.assertRaisesRegex(GameError, "don't have"):
            await self.run_game(potions.drink, ALICE, "healing")


class PotionSourceTests(GameTestCase):
    async def test_drop_gives_potions(self):
        text = await self.run_game(events.claim_drop, ALICE, {"title": "x", "reward": {"potions": 2}})
        self.assertIn("Potion of", text)
        self.assertEqual(sum((await self.run_game(potions.owned, ALICE)).values()), 2)

    async def test_top_boss_fighters_get_a_potion(self):
        await self.run_game(events.spawn_boss, "Test", 1000)
        for uid in (ALICE, BOB, CAROL, DAVE):
            await self.run_game(events.attack_boss, uid)
        await self.run_game(lambda ctx: ctx.execute("UPDATE bosses SET hp=1;"))
        self.advance(120)
        res = await self.run_game(events.attack_boss, ALICE)
        rewards = res["defeat"]["rewards"]
        self.assertEqual([bool(r["potion"]) for r in rewards], [True, True, True, False])
        for r in rewards:
            owned = sum((await self.run_game(potions.owned, r["user_id"])).values())
            self.assertEqual(owned, 1 if r["potion"] else 0)

    async def test_potions_trade_and_count_in_the_fortune(self):
        await self.run_game(potions.give, ALICE, "speed", 3)
        self.assertEqual(assets.describe("potion:speed", 2), "2 × Potion of Speed")
        await self.run_game(exchange.trade, ALICE, BOB, "potion:speed", 2, None, 0)
        self.assertEqual(await self.run_game(potions.owned, BOB), {"speed": 2})
        self.assertEqual((await self.run_game(leaderboard.fortunes))[ALICE], 40)
        with self.assertRaisesRegex(GameError, "doesn't have"):
            await self.run_game(exchange.trade, ALICE, BOB, "potion:speed", 2, None, 0)


if __name__ == "__main__":
    unittest.main()
