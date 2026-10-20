"""Day and night (2.0.8): the clock, /sleep, the night monsters and the Phantoms."""
from __future__ import annotations

from datetime import date

from game import botstate, daily, night, players, settings
from game.errors import GameError
from tests.helpers import DAY, GameTestCase

ALICE, BOB, CAROL = 1, 2, 3
HOUR, MINUTE = 3600, 60
WEAK = {"night": {"strength": {k: 0.1 for k in night.KINDS}, "phantom": {"hp": 0.1, "min_damage": 0, "max_damage": 0}}}
STRONG = {"night": {"strength": {k: 100 for k in night.KINDS}}}


class NightTestCase(GameTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for uid in (ALICE, BOB, CAROL):
            await self.run_game(players.give_emeralds, uid, 10_000)
            await self.run_game(players.set_level, uid, 10)
            await self.run_game(night.seen, uid)  # played today

    async def to_slot(self, slot: int) -> tuple[int, str]:
        """Move the clock to a monster's time tonight (tests start on Wednesday at noon)."""
        if await self.run_game(night.night_of) is None:
            self.advance(11 * HOUR)  # 23:00
        tonight = await self.run_game(night.night_of)
        at, kind = next((t, k) for s, t, k in await self.run_game(night.slots, tonight) if s == slot)
        self.now = at + 30
        return at, kind


class ClockTests(NightTestCase):
    async def test_day_and_night(self):
        self.assertIsNone(await self.run_game(night.night_of))  # noon
        self.advance(11 * HOUR)  # 23:00
        self.assertEqual(await self.run_game(night.night_of), date(2026, 10, 7))
        self.advance(5 * HOUR)  # 04:00 the next day: still the night of the 7th
        self.assertEqual(await self.run_game(night.night_of), date(2026, 10, 7))
        self.advance(3 * HOUR)  # 07:00
        self.assertIsNone(await self.run_game(night.night_of))

    async def test_the_monsters_come_inside_the_night(self):
        self.advance(11 * HOUR)
        times = await self.run_game(night.slots, date(2026, 10, 7))
        self.assertEqual(len(times), 5)
        self.assertEqual(times[-1][2], night.PHANTOM)
        self.assertEqual(times, await self.run_game(night.slots, date(2026, 10, 7)))  # always the same
        dusk, dawn = await self.run_game(lambda ctx: night._bounds(ctx, date(2026, 10, 7)))
        for _, at, _ in times:
            self.assertTrue(dusk.timestamp() + 30 * MINUTE <= at <= dawn.timestamp() - 30 * MINUTE)

    async def test_dusk_and_dawn_are_announced_once(self):
        self.assertIsNone(await self.run_game(night.to_announce))  # the first run
        self.advance(11 * HOUR)
        self.assertEqual(await self.run_game(night.to_announce), "dusk")
        self.assertIsNone(await self.run_game(night.to_announce))
        self.advance(8 * HOUR)
        self.assertEqual(await self.run_game(night.to_announce), "dawn")


class SleepTests(NightTestCase):
    async def test_sleep_at_night_once_and_a_bigger_daily(self):
        with self.assertRaisesRegex(GameError, "only sleep at night"):
            await self.run_game(night.sleep, ALICE)
        self.advance(11 * HOUR)
        await self.run_game(night.sleep, ALICE)
        with self.assertRaisesRegex(GameError, "already asleep"):
            await self.run_game(night.sleep, ALICE)
        self.advance(10 * HOUR)  # 09:00 the next day
        res = await self.run_game(daily.claim, ALICE)
        self.assertTrue(res["rested"])
        self.assertEqual(res["emeralds"], round(daily.reward_for_streak(1) * 1.25))
        self.assertFalse((await self.run_game(daily.claim, BOB))["rested"])


class MonsterTests(NightTestCase):
    async def test_a_monster_attacks_someone_awake(self):
        await self.to_slot(0)
        await self.run_game(night.sleep, ALICE)
        await self.run_game(players.set_level, CAROL, 5)  # too low
        res = await self.run_game(night.tick, [ALICE, BOB, CAROL])
        [a] = res["spawned"]
        self.assertEqual((a["target_id"], a["status"]), (BOB, "waiting"))
        with self.assertRaisesRegex(GameError, "not you"):
            await self.run_game(night.fight, a["attack_id"], ALICE)
        with self.assertRaisesRegex(GameError, "monsters nearby"):
            await self.run_game(night.sleep, BOB)
        self.assertEqual((await self.run_game(night.tick, [ALICE, BOB, CAROL]))["spawned"], [])  # once a slot

    async def test_nobody_awake(self):
        await self.to_slot(0)
        await self.run_game(night.sleep, ALICE)
        self.assertEqual((await self.run_game(night.tick, [ALICE]))["spawned"], [])
        row = await self.run_game(lambda ctx: dict(ctx.one("SELECT status FROM night_attacks WHERE slot=0;")))
        self.assertEqual(row["status"], "nobody")

    async def test_win_or_lose(self):
        settings.load(WEAK)
        _, kind = await self.to_slot(0)
        [a] = (await self.run_game(night.tick, [ALICE]))["spawned"]
        before = await self.run_game(players.get_emeralds, ALICE)
        a = await self.run_game(night.fight, a["attack_id"], ALICE)
        self.assertEqual((a["status"], a["amount"]), ("won", night.reward(kind)))
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), before + night.reward(kind))
        with self.assertRaisesRegex(GameError, "over"):
            await self.run_game(night.fight, a["attack_id"], ALICE)
        settings.load(STRONG)
        await self.to_slot(1)
        [a] = (await self.run_game(night.tick, [BOB]))["spawned"]
        before = await self.run_game(players.get_emeralds, BOB)
        a = await self.run_game(night.fight, a["attack_id"], BOB)
        self.assertEqual((a["status"], a["amount"]), ("lost", min(200, before // 100)))

    async def test_ignored_it_leaves_with_emeralds(self):
        await self.to_slot(0)
        before = await self.run_game(players.get_emeralds, ALICE)
        [a] = (await self.run_game(night.tick, [ALICE]))["spawned"]
        self.advance(16 * MINUTE)
        [gone] = (await self.run_game(night.tick, [ALICE]))["ended"]
        self.assertEqual((gone["status"], gone["amount"]), ("fled", before // 100))  # 1%
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), before - before // 100)

    async def test_the_phantom_hunts_the_sleepless(self):
        settings.load({"night": {"monsters": 0}})  # only the Phantom
        await self.to_slot(night.PHANTOM_SLOT)
        self.assertEqual((await self.run_game(night.tick, [ALICE, BOB]))["spawned"], [])  # nobody sleepless yet
        await self.run_game(lambda ctx: ctx.execute("DELETE FROM night_attacks;"))
        await self.run_game(botstate.put, "night_since", "2026-10-01")
        await self.run_game(lambda ctx: ctx.execute("UPDATE users SET last_sleep='2026-10-06' WHERE user_id=?;",
                                                    (ALICE,)))  # slept last night
        [a] = (await self.run_game(night.tick, [ALICE, BOB]))["spawned"]
        self.assertEqual((a["kind"], a["target_id"]), (night.PHANTOM, BOB))
        before = await self.run_game(players.get_emeralds, BOB)
        self.advance(16 * MINUTE)
        [gone] = (await self.run_game(night.tick, [ALICE, BOB]))["ended"]
        self.assertEqual(gone["amount"], min(500, before * 2 // 100))  # 2%

    async def test_only_active_players_are_attacked(self):
        await self.to_slot(0)  # 23:00 or later: 11 h after they played
        settings.load({"night": {"active_hours": 6}})
        self.assertEqual((await self.run_game(night.tick, [ALICE, BOB]))["spawned"], [])

    async def test_an_attack_nobody_can_see_never_happened(self):
        await self.to_slot(0)
        [a] = (await self.run_game(night.tick, [ALICE]))["spawned"]
        await self.run_game(night.unposted, a["attack_id"])
        self.advance(16 * MINUTE)
        self.assertEqual((await self.run_game(night.tick, [ALICE]))["ended"], [])  # nothing lost
        self.assertEqual((await self.run_game(night.get, a["attack_id"]))["status"], "nobody")

    async def test_a_late_slot_is_skipped(self):
        at, _ = await self.to_slot(0)
        self.now = at + 11 * MINUTE  # the bot was off
        self.assertEqual((await self.run_game(night.tick, [ALICE]))["spawned"], [])
