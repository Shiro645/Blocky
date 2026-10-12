"""Players blocked from Blocky by the staff."""
from __future__ import annotations

from game import restrictions
from game.errors import GameError
from tests.helpers import GameTestCase

STEVE, ALEX, STAFF = 1, 2, 9
HOUR = 3600


class BlockTests(GameTestCase):
    async def test_a_timed_block_ends_by_itself(self):
        block = await self.run_game(restrictions.ban, STEVE, 2 * HOUR, "Bug abuse", STAFF)
        self.assertEqual((block["until"] - block["at"], block["before"]), (2 * HOUR, None))
        self.assertIn(STEVE, await self.run_game(restrictions.active))
        self.advance(2 * HOUR)
        self.assertEqual(await self.run_game(restrictions.active), {})

    async def test_until_lifted_and_replaced(self):
        await self.run_game(restrictions.ban, STEVE, HOUR, "Spam", STAFF)
        block = await self.run_game(restrictions.ban, STEVE, None, "Again", STAFF)
        self.assertIsNone(block["until"])
        self.assertEqual(block["before"]["reason"], "Spam")
        self.advance(1000 * HOUR)
        self.assertEqual((await self.run_game(restrictions.active))[STEVE]["reason"], "Again")
        await self.run_game(restrictions.unban, STEVE)
        with self.assertRaisesRegex(GameError, "isn't blocked"):
            await self.run_game(restrictions.unban, STEVE)
        with self.assertRaisesRegex(GameError, "isn't blocked"):
            await self.run_game(restrictions.unban, ALEX)
