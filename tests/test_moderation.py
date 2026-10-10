from __future__ import annotations

import unittest

from game import moderation, settings
from game.errors import GameError
from tests.helpers import DAY, GameTestCase

HOUR = 3600
MOD, BOB = 100, 2


class DurationTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(moderation.parse_duration("10m"), 600)
        self.assertEqual(moderation.parse_duration("2h"), 7200)
        self.assertEqual(moderation.parse_duration("1d12h"), 36 * HOUR)
        self.assertEqual(moderation.parse_duration("1 w"), 7 * DAY)
        for perm in ("perm", "Permanent", "", None):
            with self.subTest(perm=perm):
                self.assertIsNone(moderation.parse_duration(perm))
        for bad in ("10", "abc", "10x", "30s", "2h abc", "400d"):
            with self.subTest(bad=bad), self.assertRaises(GameError):
                moderation.parse_duration(bad)

    def test_format(self):
        self.assertEqual(moderation.format_duration(None), "permanent")
        self.assertEqual(moderation.format_duration(36 * HOUR), "1d 12h")
        self.assertEqual(moderation.format_duration(8 * DAY + 90), "1w 1d 1m")


class SanctionTests(GameTestCase):
    async def test_warnings_and_automatic_mutes(self):
        results = [await self.run_game(moderation.warn, BOB, f"spam {i}", MOD) for i in range(5)]
        self.assertEqual([r["count"] for r in results], [1, 2, 3, 4, 5])
        self.assertEqual([r["auto_mute"] for r in results], [None, None, HOUR, None, DAY])

    async def test_warnings_expire(self):
        await self.run_game(moderation.warn, BOB, "old", MOD)
        self.advance(31 * DAY)
        res = await self.run_game(moderation.warn, BOB, "new", MOD)
        self.assertEqual(res["count"], 1)
        settings.load({"moderation": {"warn_expire_days": 0}})
        self.assertEqual(len(await self.run_game(moderation.warns, BOB)), 2)

    async def test_remove_and_clear_warnings(self):
        first = (await self.run_game(moderation.warn, BOB, "a", MOD))["sanction"]
        await self.run_game(moderation.warn, BOB, "b", MOD)
        await self.run_game(moderation.remove_warn, first["sanction_id"], MOD)
        self.assertEqual(len(await self.run_game(moderation.warns, BOB)), 1)
        with self.assertRaisesRegex(GameError, "already removed"):
            await self.run_game(moderation.remove_warn, first["sanction_id"], MOD)
        with self.assertRaisesRegex(GameError, "doesn't exist"):
            await self.run_game(moderation.remove_warn, 999, MOD)
        self.assertEqual(await self.run_game(moderation.clear_warns, BOB, MOD), 1)
        self.assertEqual(await self.run_game(moderation.warns, BOB), [])

    async def test_a_new_mute_replaces_the_old_one(self):
        await self.run_game(moderation.add, BOB, "mute", "a", MOD, HOUR)
        second = await self.run_game(moderation.add, BOB, "mute", "b", MOD, DAY)
        self.assertEqual((await self.run_game(moderation.active, BOB, "mute"))["sanction_id"], second["sanction_id"])
        lifted = await self.run_game(moderation.lift, BOB, "mute", MOD)
        self.assertEqual(len(lifted), 1)
        self.assertIsNone(await self.run_game(moderation.active, BOB, "mute"))

    async def test_long_mutes_are_renewed(self):
        mute = await self.run_game(moderation.add, BOB, "mute", "perm", MOD, None)
        until = await self.run_game(moderation.timeout_until, mute)
        self.assertEqual(until, int(self.now + moderation.MAX_TIMEOUT))
        self.assertEqual([r["sanction_id"] for r in (await self.run_game(moderation.due))["renew"]], [mute["sanction_id"]])
        await self.run_game(moderation.set_applied, mute["sanction_id"], until)
        self.assertEqual((await self.run_game(moderation.due))["renew"], [])
        self.advance(moderation.MAX_TIMEOUT - HOUR)  # less than a day left: renew
        self.assertEqual(len((await self.run_game(moderation.due))["renew"]), 1)

    async def test_short_mute_is_not_renewed_and_ends(self):
        mute = await self.run_game(moderation.add, BOB, "mute", "spam", MOD, HOUR)
        until = await self.run_game(moderation.timeout_until, mute)
        self.assertEqual(until, int(self.now + HOUR))
        await self.run_game(moderation.set_applied, mute["sanction_id"], until)
        self.assertEqual((await self.run_game(moderation.due))["renew"], [])
        self.advance(HOUR)
        due = await self.run_game(moderation.due)
        self.assertEqual([r["sanction_id"] for r in due["unmuted"]], [mute["sanction_id"]])
        self.assertIsNone(await self.run_game(moderation.active, BOB, "mute"))

    async def test_temporary_bans_expire(self):
        await self.run_game(moderation.add, BOB, "ban", "cheat", MOD, DAY)
        await self.run_game(moderation.add, 3, "ban", "forever", MOD, None)
        self.assertEqual((await self.run_game(moderation.due))["unban"], [])
        self.advance(DAY)
        due = await self.run_game(moderation.due)
        self.assertEqual([r["user_id"] for r in due["unban"]], [BOB])
        self.assertIsNotNone(await self.run_game(moderation.active, 3, "ban"))

    async def test_history(self):
        await self.run_game(moderation.warn, BOB, "spam", MOD)
        await self.run_game(moderation.add, BOB, "kick", "rude", MOD)
        await self.run_game(moderation.add, BOB, "mute", "again", MOD, HOUR)
        h = await self.run_game(moderation.history, BOB)
        self.assertEqual([r["kind"] for r in h["rows"]], ["mute", "kick", "warn"])
        self.assertEqual((h["total"], h["warns"]), (3, 1))
        self.assertIsNotNone(h["mute"])
        self.assertIsNone(h["ban"])


if __name__ == "__main__":
    unittest.main()
